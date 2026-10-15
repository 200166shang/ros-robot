"""应用主流程：接纳文本、暂停输入、会话决定、Agent、输出和恢复。"""

import asyncio
import math
import re
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional, Protocol

from robot_agent.conversation.agent import Agent
from robot_agent.results import TurnResult, VoiceRecord, make_result
from robot_agent.shutdown import ShutdownError, finish_tasks
from robot_agent.voice.live_input import SpeechInput
from robot_agent.voice.output import Playback, SpeechOutput, VoiceOutput
from robot_agent.voice.session import VoiceSession


class RecordingInput(Protocol):
    """独立文件识别Seam，不要求持续监听能力。"""

    async def recognize(self, path: Path, timeout: float) -> str:
        """验证并识别完整文件，输入失败不能启动Agent。"""
        ...

    def stop(self) -> None:
        """同步停止新文件任务与重试。"""
        ...

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """取消文件识别并释放连接。"""
        ...


class AgentApplication:
    """事件循环持有处理状态；需要等待的入口均由调用者直接 await。"""

    def __init__(
        self,
        agent: Agent,
        speech_input: Optional[SpeechInput],
        speech_output: SpeechOutput,
        output_dir: Path,
        music_playing: Callable[[], bool],
        playback: Optional[Playback] = None,
        silence_timeout: float = 120.0,
        speech_timeout: float = 60.0,
        tts_attempts: int = 3,
        failure_threshold: int = 5,
        retry_delay: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        recording_input: Optional[RecordingInput] = None,
        shutdown_timeout: float = 5.0,
    ) -> None:
        """接管Agent、会话、持续输入和独立文件识别的资源所有权。"""
        if not math.isfinite(speech_timeout) or speech_timeout <= 0:
            raise ValueError("超时必须为正有限秒数")
        if tts_attempts < 1 or failure_threshold < 1:
            raise ValueError("重试与降级阈值至少为一")
        if not math.isfinite(retry_delay) or retry_delay < 0:
            raise ValueError("重试间隔必须为非负有限秒数")
        if not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout 必须为正有限秒数")
        self._shutdown_timeout = shutdown_timeout
        self._active: Optional[asyncio.Task] = None
        self._turn_text = ""
        self._agent = agent
        self._input = speech_input
        self._recording = recording_input
        self._output = VoiceOutput(
            speech_output,
            output_dir,
            playback,
            speech_timeout,
            tts_attempts,
            failure_threshold,
            retry_delay,
        )
        self._session = VoiceSession(silence_timeout)
        self._music_playing = music_playing
        self._speech_timeout = speech_timeout
        self._clock = clock
        self._closed = False
        self._processing = False
        self._closing: Optional[asyncio.Task] = None
        self._shutdown_deadline: Optional[float] = None
        self._result_at_stop: Optional[TurnResult] = None

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
        assert self._input is not None, "持续运行需要麦克风输入"
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
        self._active = asyncio.current_task()
        self._turn_text = text
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
            if self._input is not None:
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
                if paused and not self._closed and self._input is not None:
                    self._input.resume()
                if heard_input and result.status not in (
                    "ignored",
                    "filtered",
                ):
                    self._session.mark_activity(self._clock())
            finally:
                self._processing = False
                self._active = None

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
        self._active = asyncio.current_task()
        self._turn_text = ""
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
            self._active = None
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
        self._active = asyncio.current_task()
        self._turn_text = ""
        try:
            if self._input is not None:
                self._input.pause()
            result = await self._agent.reconcile(turn_id)
            return await self._output.complete(
                result, "", self._session.state, reconcile_id=turn_id
            )
        finally:
            try:
                if not self._closed and self._input is not None:
                    self._input.resume()
                self._session.mark_activity(self._clock())
            finally:
                self._processing = False
                self._active = None

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

    @property
    def shutdown_timeout(self) -> float:
        """正式入口复用已验证配置，不在各模块重新创建总预算。"""
        return self._shutdown_timeout

    @property
    def shutdown_deadline(self) -> Optional[float]:
        """第一次关闭建立的期限供最终ROS资源收尾复用。"""
        return self._shutdown_deadline

    def stop(self) -> None:
        """退出入口同步停止准入，ROS接线第一次等待前即可调用。"""
        if self._closed:
            return
        self._result_at_stop = self._agent.last_result
        self._closed = True
        self._agent.stop()
        self._output.cancel()
        if self._input is not None:
            self._input.stop()
        if self._recording is not None and self._recording is not self._input:
            self._recording.stop()

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """立即停止新回合、动作和重试，唯一清理任务使用同一绝对期限。"""
        if self._closing is None:
            deadline = (
                time.monotonic() + self._shutdown_timeout
                if deadline is None
                else deadline
            )
            self._shutdown_deadline = deadline
            self.stop()
            self._closing = asyncio.create_task(
                self._close_resources(deadline, self._result_at_stop)
            )
        await asyncio.shield(self._closing)

    async def _close_resources(
        self, deadline: float, original_result: Optional[TurnResult]
    ) -> None:
        """输入、模型和输出并行回收；原动作等待期间ROS回执继续交付。"""
        tasks = [
            asyncio.create_task(self._agent.aclose(deadline)),
            asyncio.create_task(self._output.aclose(deadline)),
        ]
        if self._input is not None:
            tasks.append(
                asyncio.create_task(
                    finish_tasks(
                        [asyncio.create_task(self._input.aclose(deadline))],
                        deadline,
                    )
                )
            )
        if self._recording is not None and self._recording is not self._input:
            tasks.append(
                asyncio.create_task(
                    finish_tasks(
                        [
                            asyncio.create_task(
                                self._recording.aclose(deadline)
                            )
                        ],
                        deadline,
                    )
                )
            )
        errors = []
        try:
            # 同一期限内领取所有故障，单个Closer不跳过其他资源。
            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors.extend(
                result
                for result in results
                if isinstance(result, BaseException)
            )
        finally:
            active = self._active
            if active is not None and active is not asyncio.current_task():
                if not active.done():
                    active.cancel()
                try:
                    await finish_tasks([active], deadline)
                except BaseException as error:
                    errors.append(error)
            result = self._agent.last_result
            recorded = self._output.last_record
            if result is not None and (
                result is not original_result
                or (
                    recorded is not None and recorded.turn_id == result.turn_id
                )
            ):
                try:
                    self._output.save_shutdown(
                        result, self._turn_text, self._session.state
                    )
                except OSError as error:
                    errors.append(error)
        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise ShutdownError(errors)
