"""语音回合输出：集中合成恢复、播放与原回合产物关联。"""

import json
import threading
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol


class SpeechOutput(Protocol):
    """流式合成 Adapter；完整成功才提交可试听 WAV 文件。"""

    def synthesize(self, text: str, destination: Path, timeout: float) -> None:
        """按期限合成，失败抛出 I/O 异常，不能留下成功文件。"""
        ...

    def close(self) -> None:
        """释放合成连接。"""
        ...


class VoiceOutput:
    """拥有输出状态；普通回合与显式核对一次完成输出及记录。"""

    def __init__(
        self,
        speech_output: SpeechOutput,
        output_dir: Path,
        playback: Optional[Callable[[Path], None]],
        speech_timeout: float,
        tts_attempts: int,
        failure_threshold: int,
        retry_delay: float,
    ) -> None:
        """接管合成 Adapter、播放回调及输出产物目录。"""
        self._output = speech_output
        self._directory = Path(output_dir).expanduser().resolve()
        self._directory.mkdir(parents=True, exist_ok=True)
        self._playback = playback
        self._speech_timeout = speech_timeout
        self._tts_attempts = tts_attempts
        self._failure_threshold = failure_threshold
        self._retry_delay = retry_delay
        self._closed = threading.Event()
        self._failures = 0
        self._tts_enabled = True

    def complete(
        self,
        result: Dict,
        text: str,
        session_state: str,
        *,
        reconcile_id: Optional[str] = None,
        input_failed: bool = False,
    ) -> Dict:
        """按入口资格输出并保存；核对从原记录恢复文本，不提交动作。"""
        excluded = (
            ("busy",)
            if reconcile_id is not None
            else ("ignored", "filtered", "busy")
        )
        if not input_failed and result["status"] not in excluded:
            self._speak(result)
        if reconcile_id is not None:
            record = self._directory / (reconcile_id + ".json")
            if record.is_file():
                text = json.loads(record.read_text(encoding="utf-8"))[
                    "transcript"
                ]
        return self._save(result, text, session_state)

    def enable_tts(self) -> None:
        """显式清除连续失败并恢复后续回合合成，不重放既有回合。"""
        self._failures = 0
        self._tts_enabled = True

    def cancel(self) -> None:
        """终止合成重试等待并禁止后续播放，连接由关闭阶段释放。"""
        self._closed.set()

    def close(self) -> None:
        """关闭合成 Adapter，取消状态在输入清理前设置。"""
        self.cancel()
        self._output.close()

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

    def _save(self, result: Dict, text: str, session_state: str) -> Dict:
        """按 turn_id 关联识别、动作、回复和音频，原子保存记录。"""
        result["transcript"] = text
        result["session_state"] = session_state
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
