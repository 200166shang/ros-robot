"""动作执行与核对：集中持有调用、期限、执行事实和未知状态。"""

import time
from concurrent.futures import Future, wait
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence

from robot_agent.actions.registry import (
    CONFIRMED_SUCCESS,
    ActionCommand,
    ActionRegistry,
)
from robot_agent.calls import start_call
from robot_agent.results import ActionOutcome, ActionReceipt, ExecutionResult


@dataclass(frozen=True)
class _PendingAction:
    """超时调用与原回合记录，必须核对设备最终回执才能恢复接入。"""

    call: Future
    turn_id: str
    actions: List[ActionOutcome]
    tool_call_id: Optional[str] = None


def confirmed_action_reply(actions: List[ActionOutcome]) -> str:
    """仅根据已确认回执回复，不采用模型执行前的成功承诺。"""
    labels = {
        "simulated_success": "模拟成功",
        "real_success": "真实接口确认成功",
        "failed": "失败",
        "unknown": "结果未知",
        "not_executed": "未执行",
    }
    return (
        "；".join(
            action.name
            + "："
            + labels[action.status]
            + ("，" + action.detail if action.detail else "")
            for action in actions
        )
        + "。"
    )


class ActionExecutionError(Exception):
    """执行流程异常，携带已提交动作快照，交互层不得将其写入记忆。"""

    def __init__(self, result: ExecutionResult) -> None:
        """保留原错误分类与动作事实，不暴露内部异常信息。"""
        super().__init__(result.reply)
        self.result = result


class ActionExecution:
    """单一调用者使用；集中持有顺序执行与显式核对的事实。"""

    def __init__(self, actions: ActionRegistry, timeout: float) -> None:
        """接收已配置的动作注册表与交互层已校验的期限。"""
        self._actions = actions
        self._action_timeout = timeout
        self._pending_action: Optional[_PendingAction] = None

    @property
    def blocked(self) -> bool:
        """未知动作即使调用已结束，也必须显式核对后才能恢复。"""
        return self._pending_action is not None

    def execute(
        self,
        commands: Sequence[ActionCommand],
        turn_id: str,
        tool_call_id: Optional[str] = None,
    ) -> ExecutionResult:
        """执行已校验动作；须先确认未阻塞，流程异常携带事实抛出。"""
        # 1. 建立全表记录，后续失败不能丢弃已提交动作与剩余项。
        outcomes = [
            ActionOutcome(command.name, command.parameters)
            for command in commands
        ]
        try:
            self._execute_actions(commands, outcomes, turn_id, tool_call_id)
        except Exception as error:
            raise ActionExecutionError(
                ExecutionResult(
                    turn_id,
                    "failed",
                    "动作执行流程异常，请核对执行记录。",
                    tuple(outcomes),
                    tool_call_id,
                )
            ) from error

        # 2. 报告只依据执行事实，异常也必须保留原记录。
        return self._report_actions(turn_id, outcomes, tool_call_id)

    def reconcile(self, turn_id: str) -> ExecutionResult:
        """只核对原调用的迟到回执，不重新执行；未知或异常回执不能解除阻塞。"""
        pending = self._pending_action
        if pending is None or pending.turn_id != turn_id:
            return ExecutionResult(
                turn_id, "rejected", "没有匹配的待核对动作回合。", ()
            )
        if not pending.call.done():
            return ExecutionResult(
                turn_id,
                "failed",
                "调用仍在执行，结果未知。",
                tuple(pending.actions),
                pending.tool_call_id,
            )

        try:
            receipt = pending.call.result()
        except Exception:
            receipt = ActionReceipt("unknown")
        confirmed = (
            receipt.status in CONFIRMED_SUCCESS or receipt.status == "failed"
        )
        if not confirmed:
            return ExecutionResult(
                turn_id,
                "failed",
                "设备最终状态仍未知，请核实设备状态后重新启动入口。",
                tuple(pending.actions),
                pending.tool_call_id,
            )

        # 仅替换超时项，未执行的后续动作保持原状，绝不补执行。
        outcomes = [
            replace(
                action,
                status=receipt.status,
                detail=receipt.detail,
                data=receipt.data,
            )
            if action.status == "unknown"
            else action
            for action in pending.actions
        ]
        self._pending_action = None
        return self._report_actions(turn_id, outcomes, pending.tool_call_id)

    def _execute_actions(
        self,
        commands: Sequence[ActionCommand],
        outcomes: List[ActionOutcome],
        turn_id: str,
        tool_call_id: Optional[str],
    ) -> None:
        """按序提交调用；超时或未知回执保留 Future 供核对。"""
        for index, command in enumerate(commands):
            outcome = outcomes[index]
            # 提交前先保守记为未知，任何后续异常都不会伪报未执行。
            outcomes[index] = replace(
                outcome, status="unknown", detail="已提交调用，等待设备回执"
            )
            deadline = time.monotonic() + self._action_timeout
            try:
                call = start_call(
                    lambda: self._actions.invoke(command, deadline)
                )
            except Exception:
                outcomes[index] = replace(
                    outcomes[index],
                    status="failed",
                    detail="调用提交失败，未发出设备动作",
                )
                break
            self._pending_action = _PendingAction(
                call, turn_id, outcomes, tool_call_id
            )
            if not wait(
                [call], timeout=max(0.0, deadline - time.monotonic())
            ).done:
                outcomes[index] = replace(
                    outcomes[index], detail="已发出调用超时，执行结果未知"
                )
                break

            try:
                receipt = call.result()
            except Exception:
                outcomes[index] = replace(
                    outcomes[index], detail="执行异常，无法确认设备结果"
                )
                break

            outcomes[index] = replace(
                outcomes[index],
                status=receipt.status,
                detail=receipt.detail,
                data=receipt.data,
            )
            if receipt.status == "unknown":
                break
            self._pending_action = None
            if receipt.status not in CONFIRMED_SUCCESS:
                break

    def _report_actions(
        self,
        turn_id: str,
        outcomes: List[ActionOutcome],
        tool_call_id: Optional[str] = None,
    ) -> ExecutionResult:
        """只在报告阶段捕获格式异常，始终保留完整执行记录。"""
        try:
            completed = all(
                action.status in CONFIRMED_SUCCESS for action in outcomes
            )
            return ExecutionResult(
                turn_id,
                "completed" if completed else "failed",
                confirmed_action_reply(outcomes),
                tuple(outcomes),
                tool_call_id,
            )
        except Exception:
            return ExecutionResult(
                turn_id,
                "failed",
                "执行结果回复生成失败，请查看动作记录。",
                tuple(outcomes),
                tool_call_id,
            )
