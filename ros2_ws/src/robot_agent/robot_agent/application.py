"""应用主流程：接纳文本、暂停输入、会话决定、Agent、输出和恢复。"""

import asyncio
import math
import re
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from robot_agent.conversation.agent import Agent
from robot_agent.legacy_io import (
    LegacyRecordingInput,
    LegacySpeechInput,
    LegacyVoiceOutput,
    SpeechInput,
)
from robot_agent.results import TurnResult, VoiceRecord, make_result
from robot_agent.voice.output import SpeechOutput, VoiceOutput
from robot_agent.voice.session import VoiceSession


class AgentApplication:
    """事件循环持有处理状态；需要等待的入口均由调用者直接 await。"""

    def __init__(
        self,
        agent: Agent,
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
        recognize_recording: Optional[Callable[[Path, float], str]] = None,
    ) -> None:
        """接管 Agent、会话及迁移期音频 Adapter 的资源所有权。"""
        if not math.isfinite(speech_timeout) or speech_timeout <= 0:
            raise ValueError("超时必须为正有限秒数")
        if tts_attempts < 1 or failure_threshold < 1:
            raise ValueError("重试与降级阈值至少为一")
        if not math.isfinite(retry_delay) or retry_delay < 0:
            raise ValueError("重试间隔必须为非负有限秒数")
        self._agent = agent
        self._input = LegacySpeechInput(speech_input)
        self._recording = (
            LegacyRecordingInput(recognize_recording)
            if recognize_recording is not None
            else None
        )
        self._output = LegacyVoiceOutput(
            VoiceOutput(
                speech_output,
                output_dir,
                playback,
                speech_timeout,
                tts_attempts,
                failure_threshold,
                retry_delay,
            )
        )
        self._session = VoiceSession(silence_timeout)
        self._music_playing = music_playing
        self._speech_timeout = speech_timeout
        self._clock = clock
        self._closed = False
        self._processing = False
        self._closing: Optional[asyncio.Task] = None

    @property
    def state(self) -> str:
        """处理期间保持处理状态，不推进会话静音期限。"""
        if self._closed:
            return "closed"
        if self._processing:
            return "processing"
        self.tick()
        return self._session.state

    def tick(self) -> None:
        """仅在空闲时推进静音期限。"""
        if not self._processing and not self._closed:
            self._session.tick(self._clock())

    def _rejection(self) -> Optional[VoiceRecord]:
        """关闭或忙碌时不启动新的识别、模型或动作。"""
        if self._closed:
            return VoiceRecord(
                make_result(uuid.uuid4().hex, "rejected", "语音入口已关闭。")
            )
        if self._processing:
            return VoiceRecord(
                make_result(uuid.uuid4().hex, "busy", "语音回合正在处理。")
            )
        return None

    async def run(self, on_result: Callable[[VoiceRecord], None]) -> None:
        """唯一麦克风回合循环；空闲监听推进计时，退出释放输入。"""
        try:
            while not self._closed:
                try:
                    text = await self._input.listen(0.1)
                except OSError:
                    if not self._closed:
                        result = make_result(
                            uuid.uuid4().hex,
                            "failed",
                            "持续ASR不可用，监听已停止。",
                        )
                        on_result(VoiceRecord(result, asr_status="failed"))
                    return
                if self._closed:
                    return
                if text is None:
                    self.tick()
                    continue
                result = await self.submit_transcript(text)
                if not self._closed:
                    on_result(result)
        finally:
            await self.aclose()

    async def submit_transcript(
        self, text: str, direct: bool = False
    ) -> VoiceRecord:
        """一轮主流程；有效输入暂停后才决定会话，异常仍释放处理状态。"""
        rejected = self._rejection()
        if rejected is not None:
            return rejected
        self._processing = True
        paused = False
        heard_input = False
        result = make_result(uuid.uuid4().hex, "failed", "语音回合失败。")
        try:
            # 1. 外部文本校验；空识别不延长会话期限。
            if not isinstance(text, str) or not text.strip():
                result = replace(
                    result, status="rejected", reply="未识别到有效文本。"
                )
                return await self._output.complete(
                    result, "", self._session.state, input_failed=True
                )
            heard_input = True
            paused = True
            self._input.pause()

            # 2. 会话只接收观察值，普通请求由 Agent 组织模型和动作。
            decision = (
                None
                if direct
                else self._session.decide(
                    text, self._clock(), self._music_playing()
                )
            )
            if decision is None:
                result = await self._agent.submit(text)
            else:
                result = replace(
                    result, status=decision.status, reply=decision.reply
                )

            # 3. 输出只消费执行事实，不重复模型和动作。
            return await self._output.complete(
                result, text, self._session.state
            )
        finally:
            try:
                if paused and not self._closed:
                    self._input.resume()
                if heard_input and result.status not in (
                    "ignored",
                    "filtered",
                ):
                    self._session.mark_activity(self._clock())
            finally:
                self._processing = False

    async def submit_recording(
        self, path: Path, direct: bool = True
    ) -> VoiceRecord:
        """独立 WAV 先识别文件，再进入共同文本主流程。"""
        rejected = self._rejection()
        if rejected is not None:
            return rejected
        if self._recording is None:
            return VoiceRecord(
                make_result(
                    uuid.uuid4().hex, "rejected", "此输入不支持WAV识别。"
                )
            )
        self._processing = True
        try:
            try:
                text = await self._recording.recognize(
                    Path(path), self._speech_timeout
                )
            except (OSError, TimeoutError):
                result = make_result(
                    uuid.uuid4().hex,
                    "failed",
                    "在线识别不可用，本轮未发出动作。",
                )
                return await self._output.complete(
                    result,
                    "",
                    self._session.state,
                    input_failed=True,
                    asr_status="failed",
                )
        finally:
            self._processing = False
        return await self.submit_transcript(text, direct=direct)

    async def reconcile(self, turn_id: str) -> VoiceRecord:
        """只核对原回合并重新输出记录，不提交模型或重发动作。"""
        rejected = self._rejection()
        if rejected is not None:
            return rejected
        if re.fullmatch(r"[0-9a-f]{32}", turn_id) is None:
            return VoiceRecord(
                make_result(uuid.uuid4().hex, "rejected", "回合标识无效。")
            )
        self._processing = True
        try:
            self._input.pause()
            result = await self._agent.reconcile(turn_id)
            return await self._output.complete(
                result, "", self._session.state, reconcile_id=turn_id
            )
        finally:
            try:
                if not self._closed:
                    self._input.resume()
                self._session.mark_activity(self._clock())
            finally:
                self._processing = False

    async def clear_memory(self) -> TurnResult:
        """空闲时由同一应用清空记忆。"""
        rejected = self._rejection()
        return (
            rejected.turn
            if rejected is not None
            else await self._agent.clear_memory()
        )

    def enable_tts(self) -> None:
        """在回合间显式恢复在线合成。"""
        self._output.enable_tts()

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """先停止接纳与播放，再关闭输入输出；处理收尾不会恢复输入。"""
        if self._closing is None:
            self._closed = True
            self._output.cancel()
            self._closing = asyncio.create_task(
                self._close_resources(deadline)
            )
        await asyncio.shield(self._closing)

    async def _close_resources(self, deadline: Optional[float]) -> None:
        """应用持有唯一清理任务，所有退出等待者共同等待资源释放。"""
        try:
            await self._input.aclose()
        finally:
            try:
                await self._output.aclose()
            finally:
                await self._agent.aclose(deadline)
