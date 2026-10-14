"""在线文本交互主链路：单回合、先校验后执行、结果确认后回复。"""

import json
import math
import threading
import uuid
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional

from .online_actions import CONFIRMED_SUCCESS, ActionCommand, ActionRegistry
from .online_provider import TextProvider


class OperationTimeout(Exception):
    """已提交操作在期限内未得到结果。"""


@dataclass(frozen=True)
class ModelReply:
    """结构化模型回复，动作字符串尚未经过业务校验。"""

    functions: List[str]
    response: str


@dataclass(frozen=True)
class CallOutcome:
    """跨线程传回结果或异常，避免布尔值与值的隐式元组协议。"""

    value: Any = None
    error: Optional[Exception] = None


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


def confirmed_action_reply(actions: List[Dict]) -> str:
    """仅根据已确认回执回复，不采用模型执行前的成功承诺。"""
    labels = {
        "simulated_success": "模拟成功",
        "real_success": "真实接口确认成功",
        "failed": "失败",
        "unknown": "结果未知",
        "not_executed": "未执行",
    }
    return "；".join(action["name"] + "：" + labels[action["status"]] for action in actions) + "。"


class OnlineInteraction:
    """通过 submit 暴露完整回合；超时后在途动作结束前仍保持忙状态。"""

    def __init__(
        self,
        provider: TextProvider,
        actions: ActionRegistry,
        provider_timeout: float = 60.0,
        action_timeout: float = 5.0,
    ) -> None:
        """保存 provider/设备 Adapters 以及有限的执行期限。"""
        for timeout in (provider_timeout, action_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("超时必须为正有限秒数")
        self._provider = provider
        self._actions = actions
        self._provider_timeout = provider_timeout
        self._action_timeout = action_timeout
        self._turn_lock = threading.Lock()
        self._call_finished = threading.Event()
        self._call_finished.set()

    def submit(self, text: str) -> Dict:
        """提交文本，返回关联标识、回复、动作结果与回合终态；忙时立即拒绝。"""
        turn_id = uuid.uuid4().hex
        result = {"turn_id": turn_id, "status": "failed", "reply": "", "actions": []}
        if not self._turn_lock.acquire(blocking=False):
            return dict(result, status="busy", reply="正在处理上一回合，请稍后再试。")
        try:
            if not self._call_finished.is_set():
                return dict(result, status="busy", reply="上一回合的调用结果仍未知，请稍后再试。")
            if not isinstance(text, str) or not text.strip() or len(text) > 8192:
                return dict(result, status="rejected", reply="文本为空或过长。")

            # 1. 收齐 provider 输出；流式片段只拼接，绝不触发动作。
            raw = self._call_with_timeout(
                lambda: self._collect_model_output(text),
                self._provider_timeout,
            )
            model_reply = parse_model_reply(raw)

            # 2. 完整列表校验失败时零执行，聊天直接使用模型回复。
            commands = self._actions.validate(model_reply.functions)
            if not commands:
                return dict(result, status="completed", reply=model_reply.response)

            # 3. 按序执行保留重复，失败或未知停止后续动作。
            outcomes = self._execute_actions(commands)

            # 4. 根据实际回执生成回复，不采信执行前的成功承诺。
            completed = all(action["status"] in CONFIRMED_SUCCESS for action in outcomes)
            return dict(
                result,
                status="completed" if completed else "failed",
                actions=outcomes,
                reply=confirmed_action_reply(outcomes),
            )
        except OperationTimeout:
            return dict(result, reply="在线模型超时，本轮未发出动作。")
        except (ValueError, TypeError, SyntaxError):
            return dict(result, status="rejected", reply="模型输出或动作参数无效，全部动作未执行。")
        except Exception:
            return dict(result, reply="在线模型不可用，本轮未发出动作。")
        finally:
            self._turn_lock.release()

    def _execute_actions(self, commands: List[ActionCommand]) -> List[Dict]:
        """先标记全表未执行，再逐项确认；保留失败之后的未执行记录。"""
        outcomes = [
            {"name": command.name, "parameters": command.parameters, "status": "not_executed"}
            for command in commands
        ]
        for command, outcome in zip(commands, outcomes):
            try:
                receipt = self._call_with_timeout(
                    lambda: self._actions.execute(command.name, command.parameters),
                    self._action_timeout,
                )
            except OperationTimeout:
                receipt = {"status": "unknown", "detail": "已发出调用超时，执行结果未知"}
            except Exception:
                receipt = {"status": "unknown", "detail": "执行异常，无法确认设备结果"}

            outcome.update(status=receipt["status"], detail=receipt.get("detail", ""))
            if outcome["status"] not in CONFIRMED_SUCCESS:
                break
        return outcomes

    def _collect_model_output(self, text: str) -> str:
        """接受完整字符串或增量字符串流，并限制总输出大小。"""
        output = self._provider.complete(text, self._provider_timeout)
        chunks = [output] if isinstance(output, str) else output
        raw = ""
        for chunk in chunks:
            if not isinstance(chunk, str):
                raise ValueError("流式片段不是字符串")
            raw += chunk
            if len(raw.encode("utf-8")) > 65536:
                raise ValueError("模型输出过长")
        return raw

    def _call_with_timeout(self, operation: Callable[[], Any], timeout: float) -> Any:
        """限制等待时间；保留在途标识，避免超时动作与下一轮重叠。"""
        outcomes: Queue[CallOutcome] = Queue(maxsize=1)
        self._call_finished.clear()

        def run():
            """把结果或异常交还主链路，并释放在途标识。"""
            try:
                outcome = CallOutcome(value=operation())
            except Exception as error:
                outcome = CallOutcome(error=error)

            # 必须先清除在途状态再交还结果，避免下一次调用读到旧线程的释放事件。
            self._call_finished.set()
            outcomes.put(outcome)

        threading.Thread(target=run, daemon=True).start()
        try:
            outcome = outcomes.get(timeout=timeout)
        except Empty:
            raise OperationTimeout() from None
        if outcome.error is not None:
            raise outcome.error
        return outcome.value
