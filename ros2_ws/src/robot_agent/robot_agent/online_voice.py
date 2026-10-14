"""语音交互 Implementation：会话状态、半双工交接与合成恢复。"""

import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from .online_interaction import OnlineInteraction, make_result

WAKE_WORDS = tuple(
    name * 2 for name in ("小沫", "小莫", "小墨", "小末", "小陌", "小默")
)
SLEEP_COMMANDS = frozenset(
    (
        "休息",
        "睡觉",
        "晚安",
        "再见",
        "拜拜",
        "不聊了",
        "不说了",
        "我要休息",
        "我要睡觉",
        "我要走了",
        "先这样",
        "就这样",
        "好了",
        "够了",
        "结束对话",
        "停止对话",
        "我要去休息",
        "我要去睡觉",
        "我要去忙",
        "我要去工作",
        "休息一下",
        "睡一下",
        "小憩",
        "打盹",
        "午休",
        "夜宵",
    )
)
MUSIC_CONTROLS = (
    "关闭",
    "停止",
    "关掉音乐",
    "下一首",
    "切歌",
    "换歌",
    "跳过",
    "下一曲",
    "上一首",
    "上一曲",
    "前一首",
    "播放音乐",
    "开始播放",
    "继续播放",
    "恢复播放",
    "音量",
    "声音",
    "大小声",
    "静音",
)


class SpeechInput(Protocol):
    """在线识别 Adapter；暂停仅阻止输入，不代表会话休眠。"""

    def recognize(self, path: Path, timeout: float) -> str:
        """识别 PCM16 单声道 16kHz WAV；失败抛出 I/O 异常。"""
        ...

    def pause(self) -> None:
        """暂停有效音频；活跃连接只发送静音保活。"""
        ...

    def resume(self) -> None:
        """恢复接收有效音频。"""
        ...

    def close(self) -> None:
        """关闭连接和识别资源。"""
        ...


class SpeechOutput(Protocol):
    """流式合成 Adapter；完整成功才提交可试听 WAV 文件。"""

    def synthesize(self, text: str, destination: Path, timeout: float) -> None:
        """按期限合成，失败抛出 I/O 异常，不能留下成功文件。"""
        ...

    def close(self) -> None:
        """释放合成连接。"""
        ...


class OnlineVoice:
    """单回合语音 Interface；录音绕过唤醒，识别事件遵循连续会话。"""

    def __init__(
        self,
        interaction: OnlineInteraction,
        speech_input: SpeechInput,
        speech_output: SpeechOutput,
        output_dir: Path,
        music_playing: Callable[[], bool],
        playback: Optional[Callable[[Path], None]] = None,
        silence_timeout: float = 120.0,
        speech_timeout: float = 60.0,
        tts_attempts: int = 3,
        failure_threshold: int = 5,
        retry_delay: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """保存实际变化的 provider/设备 Adapters，校验外部运行参数。"""
        for value in (silence_timeout, speech_timeout):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("超时必须为正有限秒数")
        if tts_attempts < 1 or failure_threshold < 1:
            raise ValueError("重试与降级阈值至少为一")
        if not math.isfinite(retry_delay) or retry_delay < 0:
            raise ValueError("重试间隔必须为非负有限秒数")
        self._interaction = interaction
        self._input = speech_input
        self._output = speech_output
        self._directory = Path(output_dir).expanduser().resolve()
        self._directory.mkdir(parents=True, exist_ok=True)
        self._music_playing = music_playing
        self._playback = playback
        self._silence_timeout = silence_timeout
        self._speech_timeout = speech_timeout
        self._tts_attempts = tts_attempts
        self._failure_threshold = failure_threshold
        self._retry_delay = retry_delay
        self._clock = clock
        self._last_activity = clock()
        self._awake = False
        self._closed = threading.Event()
        self._turn = threading.Lock()
        self._failures = 0
        self._tts_enabled = True

    @property
    def state(self) -> str:
        """公开会话快照；处理回合时不因静音计时而进入待机。"""
        if self._closed.is_set():
            return "closed"
        if self._turn.locked():
            return "processing"
        self.tick()
        return "listening" if self._awake else "standby"

    def tick(self) -> None:
        """静音期限到达时回到待机，可由 ROS 定时器驱动。"""
        if not self._turn.locked() and self._awake:
            if self._clock() - self._last_activity >= self._silence_timeout:
                self._awake = False

    def submit_recording(self, path: Path, direct: bool = True) -> Dict:
        """真实识别录音后提交；direct 为单回合免唤醒入口。"""
        return self._submit(path=path, direct=direct)

    def submit_transcript(self, text: str, direct: bool = False) -> Dict:
        """接收最终识别事件，应用唤醒、音乐过滤与连续会话规则。"""
        return self._submit(text=text, direct=direct)

    def reconcile(self, turn_id: str) -> Dict:
        """复用迟到动作回执核对，不重发动作，更新关联文本与语音。"""
        if re.fullmatch(r"[0-9a-f]{32}", turn_id) is None:
            return make_result(uuid.uuid4().hex, "rejected", "回合标识无效。")
        return self._submit(reconcile_turn_id=turn_id)

    def enable_tts(self) -> None:
        """显式恢复连续失败后的合成，下一回合重新尝试在线 provider。"""
        if not self._turn.acquire(blocking=False):
            raise RuntimeError("回合忙碌时不能重置合成状态")
        try:
            self._failures = 0
            self._tts_enabled = True
        finally:
            self._turn.release()

    def _submit(
        self,
        text: str = "",
        path: Optional[Path] = None,
        direct: bool = False,
        reconcile_turn_id: Optional[str] = None,
    ) -> Dict:
        """集中组织识别、状态门控、动作、合成和采集恢复。"""
        turn_id = uuid.uuid4().hex
        if self._closed.is_set():
            return make_result(turn_id, "rejected", "语音入口已关闭。")
        if not self._turn.acquire(blocking=False):
            return make_result(turn_id, "busy", "正在处理上一回合。")
        paused = False
        result = make_result(turn_id, "failed", "语音回合失败。")
        try:
            if reconcile_turn_id is not None:
                paused = True
                self._input.pause()
                result = self._interaction.reconcile(reconcile_turn_id)
                if result["status"] != "busy":
                    self._speak(result)
                record = self._directory / (reconcile_turn_id + ".json")
                if record.is_file():
                    text = json.loads(record.read_text(encoding="utf-8"))[
                        "transcript"
                    ]
                return self._save(result, text)

            # 1. 输入必须来自真实录音识别或已完成的识别事件。
            if path is not None:
                try:
                    text = self._input.recognize(
                        Path(path), self._speech_timeout
                    )
                except (OSError, TimeoutError):
                    result["reply"] = "在线识别不可用，本轮未发出动作。"
                    result["asr_status"] = "failed"
                    return self._save(result, "")
            if not isinstance(text, str) or not text.strip():
                result.update(status="rejected", reply="未识别到有效文本。")
                return self._save(result, "")
            clean = re.sub(r"[^\w]", "", text)

            paused = True
            self._input.pause()

            # 2. 单回合录音不改变会话；普通输入需要唤醒且遵循音乐过滤。
            if not direct:
                if (
                    self._clock() - self._last_activity
                    >= self._silence_timeout
                ):
                    self._awake = False
                wake = next(
                    (word for word in WAKE_WORDS if word in clean), None
                )
                if wake is not None:
                    self._awake = True
                    self._last_activity = self._clock()
                    result.update(status="woken", reply="我在，请说。")
                elif not self._awake:
                    result.update(status="ignored", reply="等待唤醒词。")
                    return self._save(result, text)
                elif clean in SLEEP_COMMANDS:
                    self._awake = False
                    result.update(status="sleeping", reply="好的，进入待机。")
                elif self._music_playing() and not any(
                    word in clean for word in MUSIC_CONTROLS
                ):
                    result.update(
                        status="filtered", reply="音乐期间仅接收控制指令。"
                    )
                    return self._save(result, text)
                else:
                    result = self._interaction.submit(text)
            else:
                result = self._interaction.submit(text)

            # 3. 模型与动作只运行一次；仅合成可信回复，重试不重复动作。
            if result["status"] == "busy":
                return self._save(result, text)
            self._speak(result)
            return self._save(result, text)
        finally:
            # 4. 无论识别、合成、播放或保存如何退出，都释放回合所有权。
            try:
                if paused and not self._closed.is_set():
                    self._input.resume()
                if result["status"] not in ("ignored", "filtered"):
                    self._last_activity = self._clock()
            finally:
                self._turn.release()

    def _speak(self, result: Dict) -> None:
        """有限合成重试，连续回合失败后降级为文本；播放失败保留音频。"""
        result["tts_status"] = "disabled"
        if not self._tts_enabled or self._closed.is_set():
            return
        audio_path = self._directory / (result["turn_id"] + ".wav")
        for attempt in range(self._tts_attempts):
            try:
                self._output.synthesize(
                    result["reply"], audio_path, self._speech_timeout
                )
            except (OSError, TimeoutError):
                if attempt + 1 < self._tts_attempts:
                    if self._closed.wait(self._retry_delay):
                        return
                    continue
                self._failures += 1
                self._tts_enabled = self._failures < self._failure_threshold
                result["tts_status"] = (
                    "failed" if self._tts_enabled else "degraded"
                )
                return
            self._failures = 0
            result.update(tts_status="completed", audio_path=str(audio_path))
            if self._playback is not None and not self._closed.is_set():
                try:
                    self._playback(audio_path)
                except (OSError, RuntimeError):
                    result["playback_status"] = "failed"
                else:
                    result["playback_status"] = "completed"
            return

    def _save(self, result: Dict, text: str) -> Dict:
        """按 turn_id 关联识别、动作、回复和音频，原子保存记录。"""
        result["transcript"] = text
        result["session_state"] = "listening" if self._awake else "standby"
        destination = self._directory / (result["turn_id"] + ".json")
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(destination)
        return result

    def close(self) -> None:
        """停止接入并关闭在线连接；回合 finally 负责释放忙碌标识。"""
        self._closed.set()
        try:
            self._input.close()
        finally:
            self._output.close()
