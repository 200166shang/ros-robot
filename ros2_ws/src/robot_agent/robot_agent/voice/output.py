"""语音回合输出：集中合成恢复、播放与原回合产物关联。"""

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional, Protocol

from robot_agent.results import TurnResult, VoiceRecord, result_to_json
from robot_agent.voice._async_speech_task import SpeechTransportError


class SpeechOutput(Protocol):
    """流式合成 Adapter；完整成功才提交可试听 WAV 文件。"""

    async def synthesize(
        self, text: str, destination: Path, timeout: float
    ) -> None:
        """按期限合成，失败抛出 I/O 异常，不能留下成功文件。"""
        ...

    async def aclose(self) -> None:
        """释放合成连接。"""
        ...


class VoiceOutput:
    """拥有输出状态；普通回合与显式核对一次完成输出及记录。"""

    def __init__(
        self,
        speech_output: SpeechOutput,
        output_dir: Path,
        playback: Optional[Callable[[Path], Awaitable[None]]],
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
        self._closed = False
        self._active: Optional[asyncio.Task] = None
        self._closing: Optional[asyncio.Task] = None
        self._failures = 0
        self._tts_enabled = True
        self._transcripts: Dict[str, str] = {}

    async def complete(
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
            record = await self._speak(record)
        return self._save(record)

    def enable_tts(self) -> None:
        """显式清除连续失败并恢复后续回合合成，不重放既有回合。"""
        self._failures = 0
        self._tts_enabled = True

    def cancel(self) -> None:
        """停止新重试与播放，取消输出正在持有的本地I/O。"""
        self._closed = True
        if self._active is not None:
            self._active.cancel()

    async def aclose(self) -> None:
        """回收合成、播放器和延迟任务，再释放语音连接。"""
        if self._closing is None:
            self.cancel()
            self._closing = asyncio.create_task(self._close_resources())
        await asyncio.shield(self._closing)

    async def _close_resources(self) -> None:
        """清理过程独立于外部关闭等待者的取消。"""
        try:
            if self._active is not None:
                try:
                    await self._active
                except (asyncio.CancelledError, OSError):
                    pass
        finally:
            await self._output.aclose()

    async def _wait(
        self, operation: Awaitable[None], timeout: Optional[float] = None
    ) -> None:
        """保留原始本地操作，取消等待必须等待其资源清理。"""
        active = asyncio.ensure_future(operation)
        self._active = active
        try:
            if timeout is None:
                await active
            else:
                await asyncio.wait_for(active, timeout)
        finally:
            self._active = None

    async def _speak(self, record: VoiceRecord) -> VoiceRecord:
        """合成重试共享绝对期限，播放一次，失败回合才累计降级。"""
        if not self._tts_enabled or self._closed:
            return replace(record, tts_status="disabled")
        audio_path = self._directory / (record.turn_id + ".wav")
        deadline = time.monotonic() + self._speech_timeout
        record = replace(record, tts_status="failed")
        try:
            for attempt in range(self._tts_attempts):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self._closed:
                    break
                try:
                    await self._wait(
                        self._output.synthesize(
                            record.reply, audio_path, remaining
                        ),
                        remaining,
                    )
                except (OSError, asyncio.TimeoutError) as error:
                    if (
                        not isinstance(error, SpeechTransportError)
                        or attempt + 1 == self._tts_attempts
                    ):
                        break
                    delay = min(
                        self._retry_delay, max(0, deadline - time.monotonic())
                    )
                    if delay:
                        await self._wait(asyncio.sleep(delay))
                    continue
                self._failures = 0
                record = replace(
                    record, tts_status="completed", audio_path=str(audio_path)
                )
                if self._playback is not None and not self._closed:
                    record = replace(record, playback_status="failed")
                    try:
                        await self._wait(self._playback(audio_path))
                    except OSError:
                        pass
                    else:
                        record = replace(record, playback_status="completed")
                return record
        except BaseException:
            # 取消与编程错误仍向外显露；先保存当时已知的回合和输出事实。
            self._save(record)
            raise
        self._failures += 1
        self._tts_enabled = self._failures < self._failure_threshold
        return replace(
            record, tts_status="failed" if self._tts_enabled else "degraded"
        )

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
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return record
