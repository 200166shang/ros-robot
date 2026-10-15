"""在线文本交互主链路：单回合、先校验后执行、结果确认后回复。"""

import json
import math
import uuid
from concurrent.futures import Future, wait
from dataclasses import dataclass
from typing import Dict, List, Optional

from .online_actions import ActionRegistry
from .online_execution import (
    ActionExecution,
    ActionExecutionError,
    make_result,
    start_call,
)
from .online_memory import ConversationMemory
from .online_provider import TextProvider

MAX_INPUT_LENGTH = 8192
MAX_MODEL_OUTPUT_BYTES = 64 * 1024


@dataclass(frozen=True)
class ModelReply:
    """结构化模型回复，动作字符串尚未经过业务校验。"""

    functions: List[str]
    response: str


def _unique_object(pairs):
    """拒绝重复 JSON 键，避免模型输出存在歧义。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复 JSON 键")
        result[key] = value
    return result


def parse_model_reply(raw: str) -> ModelReply:
    """收齐后解析两种既有 JSON 契约，拒绝歧义字段与空回复。"""
    payload = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict):
        raise ValueError("模型输出必须为对象")
    if set(payload) == {"function", "response"}:
        functions, response = payload["function"], payload["response"]
    elif set(payload) == {"fc", "res"}:
        functions, response = payload["fc"], payload["res"]
    else:
        raise ValueError("模型输出字段不兼容")
    if not isinstance(response, str) or not response.strip():
        raise ValueError("模型回复无效")
    return ModelReply(functions, response)


class OnlineInteraction:
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
        self._memory = memory
        self._provider = provider
        self._actions = actions
        self._provider_timeout = provider_timeout
        self._provider_call: Optional[Future] = None
        self._execution = ActionExecution(actions, action_timeout)

    def submit(self, text: str) -> Dict:
        """单一调用者按序提交；模型仍在途或动作未知时不重叠执行。"""
        turn_id = uuid.uuid4().hex
        if self._execution.blocked:
            return make_result(
                turn_id,
                "busy",
                "动作结果待核对，请使用原回合标识请求核对回执。",
            )
        if self._provider_call is not None and not self._provider_call.done():
            return make_result(
                turn_id, "busy", "上一回合的模型调用仍在进行，请稍后再试。"
            )
        self._provider_call = None
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > MAX_INPUT_LENGTH
        ):
            return make_result(turn_id, "rejected", "文本为空或过长。")

        # 1. 模型调用与解析失败均发生在提交任何动作之前。
        try:
            self._provider_call = start_call(
                lambda: self._collect_model_output(
                    self._memory.context(text) if self._memory else text
                )
            )
            if not wait(
                [self._provider_call], timeout=self._provider_timeout
            ).done:
                return make_result(
                    turn_id, "failed", "在线模型超时，本轮未发出动作。"
                )
            model_reply = parse_model_reply(self._provider_call.result())
        except (ValueError, TypeError, SyntaxError):
            return make_result(
                turn_id, "rejected", "模型输出无效，全部动作未执行。"
            )
        except Exception:
            return make_result(
                turn_id, "failed", "在线模型不可用，本轮未发出动作。"
            )

        # 2. 整表校验无副作用，任一失败都保证零执行。
        try:
            commands = self._actions.validate(model_reply.functions)
        except (ValueError, TypeError, SyntaxError):
            return make_result(
                turn_id, "rejected", "动作参数无效，全部动作未执行。"
            )
        except Exception:
            return make_result(
                turn_id, "failed", "动作校验异常，全部动作未执行。"
            )
        if not commands:
            return self._remember(
                text,
                make_result(turn_id, "completed", model_reply.response),
            )

        # 3. 动作 Implementation 负责执行与核对事实，交互层更新记忆。
        try:
            result = self._execution.execute(commands, turn_id)
        except ActionExecutionError as error:
            return error.result
        return self._remember(text, result)

    def clear_memory(self) -> Dict:
        """由同一调用者清空；模型仍在途时拒绝，避免旧摘要回写。"""
        turn_id = uuid.uuid4().hex
        if self._provider_call is not None and not self._provider_call.done():
            return make_result(turn_id, "busy", "模型仍在调用，请稍后清空。")
        notices = self._memory.clear() if self._memory else []
        result = make_result(
            turn_id,
            "failed" if notices else "completed",
            "内存已清空，但持久清空失败，重启可能恢复旧摘要。"
            if notices
            else "近期上下文与持久摘要已清空。",
        )
        result["memory_warnings"] = notices
        return result

    def _remember(self, text: str, result: Dict) -> Dict:
        """在回复已确定后更新记忆；摘要超时不改变当前动作与回复事实。"""
        memory = self._memory
        if memory is None:
            return result
        self._provider_call = start_call(
            lambda: memory.record(text, result["reply"], self._summarize)
        )
        if not wait(
            [self._provider_call], timeout=self._provider_timeout
        ).done:
            result["memory_warnings"] = ["summary_timeout"]
        else:
            result["memory_warnings"] = self._provider_call.result()
        return result

    def _summarize(self, prompt: str) -> str:
        """复用在线输出契约，摘要只取文字且禁止动作。"""
        reply = parse_model_reply(self._collect_model_output(prompt))
        if reply.functions != []:
            raise ValueError("摘要不能包含动作")
        return reply.response

    def reconcile(self, turn_id: str) -> Dict:
        """核对原调用的迟到回执，执行状态由动作模块维护。"""
        return self._execution.reconcile(turn_id)

    def _collect_model_output(self, text: str) -> str:
        """接受完整字符串或增量字符串流，并限制总输出大小。"""
        output = self._provider.complete(text, self._provider_timeout)
        chunks = [output] if isinstance(output, str) else output
        raw = ""
        for chunk in chunks:
            if not isinstance(chunk, str):
                raise ValueError("流式片段不是字符串")
            raw += chunk
            if len(raw.encode("utf-8")) > MAX_MODEL_OUTPUT_BYTES:
                raise ValueError("模型输出过长")
        return raw
