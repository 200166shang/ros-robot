"""语音交互 Implementation：会话状态、半双工交接与合成恢复。"""

import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from robot_agent.conversation.interaction import OnlineInteraction, make_result

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


@dataclass
class _VoiceTurn:
    """一轮处理的结果、输入与暂停状态，由生命周期流程统一收尾。"""

    result: Dict
    text: str = ""
    paused: bool = False
    heard_input: bool = False


class OnlineVoice:
    """单一调用者逐轮语音Interface；录音验收绕过唤醒，麦克风遵循会话。"""

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
        self._processing = False
        self._failures = 0
        self._tts_enabled = True

    @property
    def state(self) -> str:
        """公开会话快照；处理回合时不因静音计时而进入待机。"""
        if self._closed.is_set():
            return "closed"
        if self._processing:
            return "processing"
        self.tick()
        return "listening" if self._awake else "standby"

    def tick(self) -> None:
        """静音期限到达时回到待机，可由 ROS 定时器驱动。"""
        if not self._processing and self._awake:
            if self._clock() - self._last_activity >= self._silence_timeout:
                self._awake = False

    def submit_recording(self, path: Path, direct: bool = True) -> Dict:
        """真实识别录音后提交；direct 为单回合免唤醒入口。"""
        return self._run_turn(
            lambda turn: self._process_recording(turn, path, direct)
        )

    def submit_transcript(self, text: str, direct: bool = False) -> Dict:
        """接收最终识别事件，应用唤醒、音乐过滤与连续会话规则。"""
        return self._run_turn(
            lambda turn: self._process_text(turn, text, direct)
        )

    def reconcile(self, turn_id: str) -> Dict:
        """复用迟到动作回执核对，不重发动作，更新关联文本与语音。"""
        if re.fullmatch(r"[0-9a-f]{32}", turn_id) is None:
            return make_result(uuid.uuid4().hex, "rejected", "回合标识无效。")
        return self._run_turn(lambda turn: self._reconcile_turn(turn, turn_id))

    def clear_memory(self) -> Dict:
        """由同一调用者清空记忆；保留模型仍在途时的执行约束。"""
        turn_id = uuid.uuid4().hex
        if self._closed.is_set():
            return make_result(turn_id, "rejected", "语音入口已关闭。")
        return self._interaction.clear_memory()

    def enable_tts(self) -> None:
        """由同一调用者在两轮之间显式恢复在线合成。"""
        self._failures = 0
        self._tts_enabled = True

    def _run_turn(self, operation: Callable[[_VoiceTurn], Dict]) -> Dict:
        """统一回合生命周期；业务入口各自处理，不调度并发输入。"""
        turn_id = uuid.uuid4().hex
        if self._closed.is_set():
            return make_result(turn_id, "rejected", "语音入口已关闭。")
        turn = _VoiceTurn(make_result(turn_id, "failed", "语音回合失败。"))
        self._processing = True
        try:
            return operation(turn)
        finally:
            # 结束处理并恢复采集；空识别不延长唤醒后的静音期限。
            try:
                if turn.paused and not self._closed.is_set():
                    self._input.resume()
                if turn.heard_input and turn.result["status"] not in (
                    "ignored",
                    "filtered",
                ):
                    self._last_activity = self._clock()
            finally:
                self._processing = False

    def _process_recording(
        self, turn: _VoiceTurn, path: Path, direct: bool
    ) -> Dict:
        """只处理录音识别及其I/O失败，成功后进入共同文本流程。"""
        try:
            text = self._input.recognize(Path(path), self._speech_timeout)
        except (OSError, TimeoutError):
            turn.result.update(
                reply="在线识别不可用，本轮未发出动作。", asr_status="failed"
            )
            return self._save(turn.result, "")
        return self._process_text(turn, text, direct)

    def _process_text(self, turn: _VoiceTurn, text: str, direct: bool) -> Dict:
        """顺序组织文本校验、会话决策、交互执行与语音记录。"""
        # 1. 外部文本或识别结果在进入会话前统一校验。
        if not isinstance(text, str) or not text.strip():
            turn.result.update(status="rejected", reply="未识别到有效文本。")
            return self._save(turn.result, "")
        turn.text = text
        turn.heard_input = True
        turn.paused = True
        self._input.pause()

        # 2. 会话规则可直接生成结果，正常请求才交给模型和动作。
        decision = self._decide_session(text, direct, turn.result["turn_id"])
        if decision is None:
            turn.result = self._interaction.submit(text)
        else:
            turn.result = decision

        # 3. 输出与保存不重复模型或动作，生命周期统一恢复采集。
        return self._finish_turn(turn)

    def _decide_session(
        self, text: str, direct: bool, turn_id: str
    ) -> Optional[Dict]:
        """集中应用会话规则；返回固定回执，None表示进入模型交互。"""
        if direct:
            return None
        clean = re.sub(r"[^\w]", "", text)
        if self._clock() - self._last_activity >= self._silence_timeout:
            self._awake = False
        if any(word in clean for word in WAKE_WORDS):
            self._awake = True
            self._last_activity = self._clock()
            return make_result(turn_id, "woken", "我在，请说。")
        if not self._awake:
            return make_result(turn_id, "ignored", "等待唤醒词。")
        if clean in SLEEP_COMMANDS:
            self._awake = False
            return make_result(turn_id, "sleeping", "好的，进入待机。")
        if self._music_playing() and not any(
            word in clean for word in MUSIC_CONTROLS
        ):
            return make_result(turn_id, "filtered", "音乐期间仅接收控制指令。")
        return None

    def _reconcile_turn(self, turn: _VoiceTurn, turn_id: str) -> Dict:
        """独立核对原动作；只关联原文本，不识别或提交新的模型请求。"""
        turn.heard_input = True
        turn.paused = True
        self._input.pause()
        turn.result = self._interaction.reconcile(turn_id)
        if turn.result["status"] != "busy":
            self._speak(turn.result)
        record = self._directory / (turn_id + ".json")
        if record.is_file():
            turn.text = json.loads(record.read_text(encoding="utf-8"))[
                "transcript"
            ]
        return self._save(turn.result, turn.text)

    def _finish_turn(self, turn: _VoiceTurn) -> Dict:
        """被忽略、过滤或执行仍在途时只记录，其余结果合成后保存。"""
        if turn.result["status"] not in ("ignored", "filtered", "busy"):
            self._speak(turn.result)
        return self._save(turn.result, turn.text)

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
        result["record_status"] = "completed"
        try:
            temporary.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(destination)
        except OSError:
            result["record_status"] = "failed"
        return result

    def close(self) -> None:
        """停止接入并关闭在线连接；回合生命周期负责清除处理标记。"""
        self._closed.set()
        try:
            self._input.close()
        finally:
            self._output.close()
