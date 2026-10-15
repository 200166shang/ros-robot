"""在线文本交互主链路：单回合、先校验后执行、结果确认后回复。"""

import asyncio
import math
import uuid
from dataclasses import replace
from typing import Optional

from robot_agent.actions.execution import (
    ActionExecution,
    ActionExecutionError,
)
from robot_agent.actions.registry import ActionRegistry
from robot_agent.calls import LegacyCall
from robot_agent.conversation.memory import ConversationMemory
from robot_agent.conversation.provider import TextProvider
from robot_agent.results import ModelReply, TurnResult, make_result

MAX_INPUT_LENGTH = 8192


class Agent:
    """单一调用者组织交互与动作核对；线程结束不等于设备确认。"""

    def __init__(
        self,
        provider: TextProvider,
        actions: ActionRegistry,
        provider_timeout: float = 60.0,
        action_timeout: float = 5.0,
        memory: Optional[ConversationMemory] = None,
    ) -> None:
        """保存 provider/设备 Adapters 以及有限的执行期限。"""
        for timeout in (provider_timeout, action_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("超时必须为正有限秒数")
        self._processing = False
        self._memory = memory
        self._provider = provider
        self._actions = actions
        self._tools = actions.tool_schema
        self._provider_timeout = provider_timeout
        self._model_io = LegacyCall()
        self._execution_io = LegacyCall()
        self._memory_io = LegacyCall()
        self._execution = ActionExecution(actions, action_timeout)

    async def submit(self, text: str) -> TurnResult:
        """单一调用者按序提交；模型仍在途或动作未知时不重叠执行。"""
        turn_id = uuid.uuid4().hex
        if self._execution.blocked:
            return make_result(
                turn_id,
                "busy",
                "动作结果待核对，请使用原回合标识请求核对回执。",
            )
        if (
            self._processing
            or self._model_io.pending
            or self._memory_io.pending
        ):
            return make_result(
                turn_id, "busy", "上一回合的模型调用仍在进行，请稍后再试。"
            )
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_INPUT_LENGTH
        ):
            return make_result(turn_id, "rejected", "文本为空或过长。")

        if self._processing:
            return make_result(turn_id, "busy", "文本回合正在处理。")
        self._processing = True
        try:
            # 1. 模型调用与解析失败均发生在提交任何动作之前。
            try:
                model_reply = await self._model_io.run(
                    lambda: self._provider.complete(
                        self._memory.context(text) if self._memory else text,
                        self._provider_timeout,
                        tools=self._tools,
                    ),
                    self._provider_timeout,
                )
                if not isinstance(model_reply, ModelReply):
                    raise ValueError("模型必须返回完整 ModelReply")
            except asyncio.TimeoutError:
                return make_result(
                    turn_id, "failed", "在线模型超时，本轮未发出动作。"
                )
            except (ValueError, TypeError, SyntaxError):
                return make_result(
                    turn_id, "rejected", "模型输出无效，全部动作未执行。"
                )
            except Exception:
                return make_result(
                    turn_id, "failed", "在线模型不可用，本轮未发出动作。"
                )

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
            except (ValueError, TypeError, SyntaxError):
                return make_result(
                    turn_id, "rejected", "动作参数无效，全部动作未执行。"
                )
            except Exception:
                return make_result(
                    turn_id, "failed", "动作校验异常，全部动作未执行。"
                )

            # 3. 动作模块维护执行事实，Agent 更新记忆。
            try:
                result = await self._execution_io.run(
                    lambda: self._execution.execute(
                        plan.commands, turn_id, tool_call.call_id
                    )
                )
            except ActionExecutionError as error:
                return TurnResult.from_execution(error.result)
            return await self._remember(
                text, TurnResult.from_execution(result)
            )
        finally:
            self._processing = False

    async def clear_memory(self) -> TurnResult:
        """由同一调用者清空；模型仍在途时拒绝，避免旧摘要回写。"""
        turn_id = uuid.uuid4().hex
        if (
            self._processing
            or self._model_io.pending
            or self._memory_io.pending
        ):
            return make_result(turn_id, "busy", "模型仍在调用，请稍后清空。")
        notices = (
            await self._memory_io.run(self._memory.clear)
            if self._memory
            else []
        )
        result = make_result(
            turn_id,
            "failed" if notices else "completed",
            "内存已清空，但持久清空失败，重启可能恢复旧摘要。"
            if notices
            else "近期上下文与持久摘要已清空。",
        )
        return replace(result, memory_warnings=tuple(notices))

    async def _remember(self, text: str, result: TurnResult) -> TurnResult:
        """在回复已确定后更新记忆；摘要超时不改变当前动作与回复事实。"""
        memory = self._memory
        if memory is None:
            return result
        try:
            notices = await self._memory_io.run(
                lambda: memory.record(text, result.reply, self._summarize),
                self._provider_timeout,
            )
        except asyncio.TimeoutError:
            notices = ["summary_timeout"]
        return replace(result, memory_warnings=tuple(notices))

    def _summarize(self, prompt: str) -> str:
        """摘要请求禁用工具，只消费模型普通文字。"""
        reply = self._provider.complete(
            prompt, self._provider_timeout, tools=None
        )
        if not isinstance(reply, ModelReply) or reply.tool_call is not None:
            raise ValueError("摘要不能包含动作")
        return reply.response

    async def reconcile(self, turn_id: str) -> TurnResult:
        """核对原调用的迟到回执，执行状态由动作模块维护。"""
        if self._processing or self._execution_io.pending:
            return make_result(uuid.uuid4().hex, "busy", "文本回合正在处理。")
        result = await self._execution_io.run(
            lambda: self._execution.reconcile(turn_id)
        )
        return TurnResult.from_execution(result)
