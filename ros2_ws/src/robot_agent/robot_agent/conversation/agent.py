"""在线文本交互主链路：单回合、先校验后执行、结果确认后回复。"""

import asyncio
import math
import time
import uuid
from dataclasses import replace
from typing import Dict, Optional

from robot_agent.actions.execution import (
    ActionExecution,
    ActionExecutionError,
)
from robot_agent.actions.registry import ActionRegistry
from robot_agent.conversation.memory import (
    MAX_SUMMARY_CHARS,
    ConversationMemory,
)
from robot_agent.conversation.provider import (
    Model,
    ModelProtocolError,
    ModelTransportError,
)
from robot_agent.results import ModelReply, TurnResult, make_result
from robot_agent.shutdown import ShutdownError, finish_tasks

MAX_INPUT_LENGTH = 8192
DEFAULT_MODEL_ATTEMPTS = 3


class Agent:
    """单一调用者组织交互与动作核对；线程结束不等于设备确认。"""

    def __init__(
        self,
        provider: Model,
        actions: ActionRegistry,
        provider_timeout: float = 60.0,
        action_timeout: float = 5.0,
        memory: Optional[ConversationMemory] = None,
        model_attempts: int = DEFAULT_MODEL_ATTEMPTS,
    ) -> None:
        """保存 provider/设备 Adapters 以及有限的执行期限。"""
        for timeout in (provider_timeout, action_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("超时必须为正有限秒数")
        if type(model_attempts) is not int or not 1 <= model_attempts <= 5:
            raise ValueError("模型尝试次数必须为 1–5 整数")
        self._model_attempts = model_attempts
        self._closed = False
        self._processing = False
        self._memory = memory
        self._provider = provider
        self._actions = actions
        self._tools = actions.tool_schema
        self._provider_timeout = provider_timeout
        self._model_task: Optional[asyncio.Task] = None
        self.last_result: Optional[TurnResult] = None
        self._execution = ActionExecution(actions, action_timeout)
        self._closing: Optional[asyncio.Task] = None

    async def submit(self, text: str) -> TurnResult:
        """单一调用者按序提交；模型仍在途或动作未知时不重叠执行。"""
        turn_id = uuid.uuid4().hex
        if self._closed:
            return make_result(turn_id, "rejected", "文本入口已关闭。")
        if self._processing:
            return make_result(turn_id, "busy", "文本回合正在处理。")
        self._observe_retired_model()
        if self._execution.blocked:
            return make_result(
                turn_id,
                "busy",
                "动作结果待核对，请使用原回合标识请求核对回执。",
            )
        if self._model_task is not None and not self._model_task.done():
            return make_result(
                turn_id, "busy", "上一回合的模型调用仍在进行，请稍后再试。"
            )
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_INPUT_LENGTH
        ):
            return make_result(turn_id, "rejected", "文本为空或过长。")

        self._processing = True
        self.last_result = make_result(
            turn_id, "failed", "回合尚未完成，未提交动作。"
        )
        try:
            # 1. 模型调用与解析失败均发生在提交任何动作之前。
            try:
                model_reply = await self._complete(
                    self._memory.context(text) if self._memory else text,
                    tools=self._tools,
                    attempts=self._model_attempts,
                )
            except asyncio.TimeoutError:
                self.last_result = make_result(
                    turn_id, "failed", "在线模型超时，本轮未发出动作。"
                )
                return self.last_result
            except ModelProtocolError:
                self.last_result = make_result(
                    turn_id, "rejected", "模型输出无效，全部动作未执行。"
                )
                return self.last_result
            except ModelTransportError:
                self.last_result = make_result(
                    turn_id, "failed", "在线模型不可用，本轮未发出动作。"
                )
                return self.last_result

            if self._closed:
                self.last_result = make_result(
                    turn_id, "failed", "入口退出，未提交动作。"
                )
                return self.last_result

            # 2. 普通聊天使用模型文字；动作整表校验后才可提交。
            tool_call = model_reply.tool_call
            if tool_call is None:
                return await self._remember(
                    text,
                    make_result(turn_id, "completed", model_reply.response),
                )
            try:
                if tool_call.name != "execute_actions":
                    raise ValueError("未知工具")
                plan = self._actions.bind_plan(tool_call.arguments)
            except ValueError:
                self.last_result = make_result(
                    turn_id, "rejected", "动作参数无效，全部动作未执行。"
                )
                return self.last_result

            # 3. 动作模块维护执行事实，Agent 更新记忆。
            try:
                result = await self._execution.execute(
                    plan, turn_id, tool_call.call_id
                )
            except ActionExecutionError as error:
                self.last_result = TurnResult.from_execution(error.result)
                raise
            return await self._remember(
                text, TurnResult.from_execution(result)
            )
        except asyncio.CancelledError:
            execution = self._execution.last_result
            if execution is not None and execution.turn_id == turn_id:
                self.last_result = TurnResult.from_execution(execution)
            elif self._closed:
                # 取消摘要不抹掉实际回复；生成退出时的新事实快照。
                assert self.last_result is not None
                self.last_result = replace(self.last_result)
            raise
        finally:
            self._processing = False

    async def clear_memory(self) -> TurnResult:
        """由同一调用者清空；模型仍在途时拒绝，避免旧摘要回写。"""
        turn_id = uuid.uuid4().hex
        if self._processing or (
            self._model_task is not None and not self._model_task.done()
        ):
            return make_result(turn_id, "busy", "模型仍在调用，请稍后清空。")
        self._observe_retired_model()
        notices = self._memory.clear() if self._memory else []
        result = make_result(
            turn_id,
            "failed" if notices else "completed",
            "内存已清空，但持久清空失败，重启可能恢复旧摘要。"
            if notices
            else "近期上下文与持久摘要已清空。",
        )
        return replace(result, memory_warnings=tuple(notices))

    async def _remember(self, text: str, result: TurnResult) -> TurnResult:
        """先保留回复与事实，再显式请求禁用工具的有界摘要。"""
        self.last_result = result
        memory = self._memory
        if memory is None:
            return result
        notices = memory.record(text, result.reply)
        prompt = memory.summary_prompt()
        if prompt is not None and not self._closed:
            try:
                reply = await self._complete(prompt, tools=None, attempts=1)
                if (
                    reply.tool_call is not None
                    or not reply.response.strip()
                    or len(reply.response) > MAX_SUMMARY_CHARS
                ):
                    raise ModelProtocolError("摘要无效")
            except asyncio.TimeoutError:
                notices.append("summary_timeout")
            except (ModelTransportError, ModelProtocolError):
                notices.append("summary_failed")
            else:
                if not self._closed:
                    notices.extend(memory.apply_summary(reply.response))
        self.last_result = replace(result, memory_warnings=tuple(notices))
        return self.last_result

    async def _complete(
        self, text: str, *, tools: Optional[Dict], attempts: int
    ) -> ModelReply:
        """保留原请求直到清理结束；等待期限不代表请求结束。"""
        deadline = time.monotonic() + self._provider_timeout
        attempt = 0
        while True:
            if self._closed:
                raise ModelTransportError("closed")
            attempt += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError
            task = asyncio.create_task(
                self._provider.complete(text, deadline, tools=tools)
            )
            task.add_done_callback(self._observe_model)
            self._model_task = task
            try:
                done, _ = await asyncio.wait({task}, timeout=remaining)
                if not done:
                    task.cancel()
                    raise asyncio.TimeoutError
                self._model_task = None
                return task.result()
            except ModelTransportError as error:
                self._model_task = None
                if not error.transient or attempt == attempts or self._closed:
                    raise
            except asyncio.CancelledError:
                task.cancel()
                raise

    def _observe_retired_model(self) -> None:
        """迟到回复只能丢弃；迟到编程错误仍向下一次调用者显露。"""
        task = self._model_task
        if task is None or not task.done():
            return
        self._model_task = None
        if task.cancelled():
            return
        try:
            task.result()
        except (ModelTransportError, ModelProtocolError):
            pass

    @staticmethod
    def _observe_model(task):
        """领取异常但保留原结果，下一次接入仍可观察迟到的编程错误。"""
        if not task.cancelled():
            task.exception()

    async def reconcile(self, turn_id: str) -> TurnResult:
        """核对原调用的迟到回执，不再包裹后台线程。"""
        if self._processing:
            return make_result(uuid.uuid4().hex, "busy", "文本回合正在处理。")
        try:
            result = await self._execution.reconcile(turn_id)
        except ActionExecutionError as error:
            self.last_result = TurnResult.from_execution(error.result)
            raise
        self.last_result = TurnResult.from_execution(result)
        return self.last_result

    def stop(self) -> None:
        """在第一次退出等待前同步停止模型重试与所有动作准入。"""
        if self._closed:
            return
        self._closed = True
        self._execution.stop()
        task = self._model_task
        if task is not None and not task.done():
            task.cancel()

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """关闭调用共享原清理；原动作仍可在剩余预算内接收回执。"""
        if self._closing is None:
            self.stop()
            self._closing = asyncio.create_task(
                self._close_resources(deadline)
            )
        await asyncio.shield(self._closing)

    async def _close_resources(self, deadline: Optional[float]) -> None:
        """无论动作收尾是否失败，模型连接和能力资源都必须尝试关闭。"""
        tasks = [asyncio.create_task(self._provider.aclose(deadline))]
        task = self._model_task
        if task is not None:
            tasks.append(task)
        errors = []
        try:
            action_result = await self._execution.aclose(
                time.monotonic() if deadline is None else deadline
            )
            if action_result is not None:
                self.last_result = TurnResult.from_execution(action_result)
        except BaseException as error:
            if (
                self._execution.blocked
                and self._execution.last_result is not None
            ):
                self.last_result = TurnResult.from_execution(
                    self._execution.last_result
                )
            errors.append(error)
        try:
            await finish_tasks(tasks, deadline)
        except BaseException as error:
            errors.append(error)
        try:
            await self._actions.aclose(deadline)
        except BaseException as error:
            errors.append(error)
        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise ShutdownError(errors)
