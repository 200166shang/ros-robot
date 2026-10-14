"""在线文本交互主链路：单回合、先校验后执行、结果确认后回复。"""

import json
import math
import threading
import uuid
from concurrent.futures import Future, wait
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .online_actions import CONFIRMED_SUCCESS, ActionCommand, ActionRegistry
from .online_provider import TextProvider


@dataclass(frozen=True)
class ModelReply:
    """结构化模型回复，动作字符串尚未经过业务校验。"""

    functions: List[str]
    response: str


@dataclass(frozen=True)
class PendingAction:
    """超时调用与原回合记录，必须核对设备最终回执才能恢复接入。"""

    call: Future
    turn_id: str
    actions: List[Dict]


def make_result(
    turn_id: str,
    status: str,
    reply: str,
    actions: Optional[List[Dict]] = None,
) -> Dict:
    """统一回合结构，返回记录快照，核对迟到回执不改写已发布结果。"""
    return {
        "turn_id": turn_id,
        "status": status,
        "reply": reply,
        "actions": [dict(action) for action in actions] if actions is not None else [],
    }


def start_call(operation: Callable[[], Any]) -> Future:
    """隔离不能保证按时返回的 I/O；Future 只传回回执，不表示调用可取消。"""
    call = Future()

    def run() -> None:
        """把 I/O 的结果或异常交给标准 Future，不操作回合业务状态。"""
        try:
            call.set_result(operation())
        except Exception as error:
            call.set_exception(error)

    threading.Thread(target=run, daemon=True, name="online-agent-io").start()
    return call


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
    """submit 组织回合；reconcile 核对超时动作，线程结束不自动恢复接入。"""

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
        self._provider_call: Optional[Future] = None
        self._pending_action: Optional[PendingAction] = None

    def submit(self, text: str) -> Dict:
        """提交文本；回合互斥、模型在途与动作待核对各自保留明确状态。"""
        turn_id = uuid.uuid4().hex
        if not self._turn_lock.acquire(blocking=False):
            return make_result(turn_id, "busy", "正在处理上一回合，请稍后再试。")
        try:
            if self._pending_action is not None:
                return make_result(
                    turn_id,
                    "busy",
                    "动作结果待核对，请使用原回合标识请求核对回执。",
                )
            if self._provider_call is not None and not self._provider_call.done():
                return make_result(turn_id, "busy", "上一回合的模型调用仍在进行，请稍后再试。")
            self._provider_call = None
            if not isinstance(text, str) or not text.strip() or len(text) > 8192:
                return make_result(turn_id, "rejected", "文本为空或过长。")

            # 1. 模型调用与解析失败均发生在提交任何动作之前。
            try:
                self._provider_call = start_call(lambda: self._collect_model_output(text))
                if not wait([self._provider_call], timeout=self._provider_timeout).done:
                    return make_result(turn_id, "failed", "在线模型超时，本轮未发出动作。")
                model_reply = parse_model_reply(self._provider_call.result())
            except (ValueError, TypeError, SyntaxError):
                return make_result(turn_id, "rejected", "模型输出无效，全部动作未执行。")
            except Exception:
                return make_result(turn_id, "failed", "在线模型不可用，本轮未发出动作。")

            # 2. 整表校验无副作用，任一失败都保证零执行。
            try:
                commands = self._actions.validate(model_reply.functions)
            except (ValueError, TypeError, SyntaxError):
                return make_result(turn_id, "rejected", "动作参数无效，全部动作未执行。")
            except Exception:
                return make_result(turn_id, "failed", "动作校验异常，全部动作未执行。")
            if not commands:
                return make_result(turn_id, "completed", model_reply.response)

            # 3. 在执行前建立完整记录，后续异常不能丢弃已提交动作的事实。
            outcomes = [
                {"name": command.name, "parameters": command.parameters, "status": "not_executed"}
                for command in commands
            ]
            try:
                self._execute_actions(commands, outcomes, turn_id)
            except Exception:
                return make_result(
                    turn_id, "failed", "动作执行流程异常，请核对执行记录。", outcomes
                )

            # 4. 回复异常仅影响本轮报告，不能把已执行动作归类为模型失败。
            return self._report_actions(turn_id, outcomes)
        finally:
            self._turn_lock.release()

    def reconcile(self, turn_id: str) -> Dict:
        """只核对原调用的迟到回执，不重新执行；未知或异常回执不能解除阻塞。"""
        if not self._turn_lock.acquire(blocking=False):
            return make_result(turn_id, "busy", "正在处理回合，请稍后核对。")
        try:
            pending = self._pending_action
            if pending is None or pending.turn_id != turn_id:
                return make_result(turn_id, "rejected", "没有匹配的待核对动作回合。")
            if not pending.call.done():
                return make_result(turn_id, "failed", "调用仍在执行，结果未知。", pending.actions)

            try:
                receipt = pending.call.result()
            except Exception:
                receipt = {"status": "unknown"}
            confirmed = receipt["status"] in CONFIRMED_SUCCESS or receipt["status"] == "failed"
            if not confirmed:
                return make_result(
                    turn_id,
                    "failed",
                    "设备最终状态仍未知，请核实设备状态后重新启动入口。",
                    pending.actions,
                )

            # 仅替换超时项，未执行的后续动作保持原状，绝不补执行。
            action = next(action for action in pending.actions if action["status"] == "unknown")
            action.update(status=receipt["status"], detail=receipt.get("detail", ""))
            self._pending_action = None
            return self._report_actions(turn_id, pending.actions)
        finally:
            self._turn_lock.release()

    def _execute_actions(
        self,
        commands: List[ActionCommand],
        outcomes: List[Dict],
        turn_id: str,
    ) -> None:
        """按序提交不可取消的调用；超时或不确定回执保留原 Future 供核对。"""
        for command, outcome in zip(commands, outcomes):
            # 提交前先保守记为未知，任何后续异常都不会伪报未执行。
            outcome.update(status="unknown", detail="已提交调用，等待设备回执")
            try:
                call = start_call(lambda: self._actions.execute(command.name, command.parameters))
            except Exception:
                outcome.update(status="failed", detail="调用提交失败，未发出设备动作")
                break
            self._pending_action = PendingAction(call, turn_id, outcomes)
            if not wait([call], timeout=self._action_timeout).done:
                outcome["detail"] = "已发出调用超时，执行结果未知"
                break

            try:
                receipt = call.result()
                outcome.update(status=receipt["status"], detail=receipt.get("detail", ""))
            except Exception:
                outcome["detail"] = "执行异常，无法确认设备结果"
                break
            if outcome["status"] == "unknown":
                break
            self._pending_action = None
            if outcome["status"] not in CONFIRMED_SUCCESS:
                break

    def _report_actions(self, turn_id: str, outcomes: List[Dict]) -> Dict:
        """只在报告阶段捕获格式异常，始终保留完整执行记录。"""
        try:
            completed = all(action["status"] in CONFIRMED_SUCCESS for action in outcomes)
            return make_result(
                turn_id,
                "completed" if completed else "failed",
                confirmed_action_reply(outcomes),
                outcomes,
            )
        except Exception:
            return make_result(
                turn_id, "failed", "执行结果回复生成失败，请查看动作记录。", outcomes
            )

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
