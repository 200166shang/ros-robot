"""语音回合输出：集中合成恢复、播放与原回合产物关联。"""

import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol

from robot_agent.results import TurnResult, VoiceRecord, result_to_json


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
        self._transcripts: Dict[str, str] = {}

    def complete(
        self,
        result: TurnResult,
        text: str,
        session_state: str,
        *,
        reconcile_id: Optional[str] = None,
        input_failed: bool = False,
        asr_status: Optional[str] = None,
    ) -> VoiceRecord:
        """按入口资格输出并保存；核对从原记录恢复文本，不提交动作。"""
        excluded = (
            ("busy",)
            if reconcile_id is not None
            else ("ignored", "filtered", "busy")
        )
        if reconcile_id is not None:
            text = self._transcripts.get(reconcile_id, text)
        record = VoiceRecord(
            result, text, session_state, asr_status=asr_status
        )
        if any(action.status == "unknown" for action in result.actions):
            self._transcripts[result.turn_id] = text
        else:
            self._transcripts.pop(result.turn_id, None)
        if not input_failed and result.status not in excluded:
            record = self._speak(record)
        return self._save(record)

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

    def _speak(self, record: VoiceRecord) -> VoiceRecord:
        """有限合成重试，连续回合失败后降级为文本；播放失败保留音频。"""
        record = replace(record, tts_status="disabled")
        if not self._tts_enabled or self._closed.is_set():
            return record
        audio_path = self._directory / (record.turn_id + ".wav")
        for attempt in range(self._tts_attempts):
            try:
                self._output.synthesize(
                    record.reply, audio_path, self._speech_timeout
                )
            except (OSError, TimeoutError):
                if attempt + 1 < self._tts_attempts:
                    if self._closed.wait(self._retry_delay):
                        return record
                    continue
                self._failures += 1
                self._tts_enabled = self._failures < self._failure_threshold
                return replace(
                    record,
                    tts_status="failed" if self._tts_enabled else "degraded",
                )
            self._failures = 0
            record = replace(
                record, tts_status="completed", audio_path=str(audio_path)
            )
            if self._playback is not None and not self._closed.is_set():
                try:
                    self._playback(audio_path)
                except (OSError, RuntimeError):
                    record = replace(record, playback_status="failed")
                else:
                    record = replace(record, playback_status="completed")
            return record
        return record

    def _save(self, record: VoiceRecord) -> VoiceRecord:
        """按 turn_id 原子保存兼容 JSON，磁盘失败独立于执行事实。"""
        destination = self._directory / (record.turn_id + ".json")
        temporary = destination.with_suffix(".json.tmp")
        record = replace(record, record_status="completed")
        try:
            temporary.write_text(
                json.dumps(
                    result_to_json(record), ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
            temporary.replace(destination)
        except OSError:
            return replace(record, record_status="failed")
        return record
