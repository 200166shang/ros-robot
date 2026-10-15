"""动作执行与核对：事件循环独占原操作与不可变结果快照。"""

import asyncio
import time
from dataclasses import dataclass, replace
from typing import List, Optional

from robot_agent.actions.registry import (
    CONFIRMED_SUCCESS,
    ActionPlan,
    ActionRegistry,
)
from robot_agent.results import ActionOutcome, ExecutionResult


@dataclass(frozen=True)
class _PendingAction:
    """未知操作的唯一归属；结束等待不取消设备请求。"""

    task: asyncio.Task
    turn_id: str
    actions: List[ActionOutcome]
    index: int
    tool_call_id: Optional[str]


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
    """编程错误继续抛出，同时携带已经提交和确认的动作事实。"""

    def __init__(self, result: ExecutionResult) -> None:
        """快照供异常调用者保存，原错误保留在 cause。"""
        super().__init__(result.reply)
        self.result = result


def _observe(task: asyncio.Task) -> None:
    """领取异常避免无人观察；核对仍从原 Task 重新抛出错误。"""
    if not task.cancelled():
        task.exception()


class ActionExecution:
    """单一调用者顺序执行计划；核对原调用，不重发或补执行余项。"""

    def __init__(self, actions: ActionRegistry, timeout: float) -> None:
        """持有动作目录、每项预算和尚未确认的唯一原操作。"""
        self._actions = actions
        self._action_timeout = timeout
        self._pending_action: Optional[_PendingAction] = None
        self._closed = False
        self.last_result: Optional[ExecutionResult] = None

    @property
    def blocked(self) -> bool:
        """Task 已完成而回执仍 unknown 时，继续阻止新计划。"""
        return self._pending_action is not None

    async def execute(
        self,
        plan: ActionPlan,
        turn_id: str,
        tool_call_id: Optional[str] = None,
    ) -> ExecutionResult:
        """整表先建事实，逐项等待回执；超时保留原 Task 供核对。"""
        if self._closed:
            raise RuntimeError("动作执行已经关闭")
        if self.blocked:
            raise RuntimeError("未知动作未核对，不能提交新计划")
        outcomes = [ActionOutcome(c.name, c.parameters) for c in plan.commands]
        try:
            for index, command in enumerate(plan.commands):
                if self._closed:
                    break
                # 1. 提交前记录 unknown，后续错误不能抹掉事实。
                outcomes[index] = replace(
                    outcomes[index],
                    status="unknown",
                    detail="已提交调用，等待设备回执",
                )
                deadline = time.monotonic() + self._action_timeout
                task = asyncio.create_task(
                    self._actions.invoke(command, deadline)
                )
                task.add_done_callback(_observe)
                self._pending_action = _PendingAction(
                    task, turn_id, outcomes, index, tool_call_id
                )
                done, _ = await asyncio.wait(
                    {task}, timeout=max(0, deadline - time.monotonic())
                )
                if not done:
                    outcomes[index] = replace(
                        outcomes[index], detail="已发出调用超时，执行结果未知"
                    )
                    break
                receipt = task.result()
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
            # 2. 回复只采用已确认事实，未知与未执行余项一起报告。
            return self._report(turn_id, outcomes, tool_call_id)
        except asyncio.CancelledError:
            self.last_result = self._snapshot(turn_id, outcomes, tool_call_id)
            raise
        except Exception as error:
            self.last_result = self._snapshot(turn_id, outcomes, tool_call_id)
            raise ActionExecutionError(self.last_result) from error

    async def reconcile(self, turn_id: str) -> ExecutionResult:
        """只读取原操作；未知或异常不能解除阻塞。"""
        pending = self._pending_action
        if pending is None or pending.turn_id != turn_id:
            return ExecutionResult(
                turn_id, "rejected", "没有匹配的待核对动作回合。", ()
            )
        if not pending.task.done():
            return self._snapshot(
                turn_id, pending.actions, pending.tool_call_id
            )
        try:
            receipt = pending.task.result()
            if receipt.status == "unknown":
                return ExecutionResult(
                    turn_id,
                    "failed",
                    "设备最终状态仍未知，请核实设备状态后重新启动入口。",
                    tuple(pending.actions),
                    pending.tool_call_id,
                )
            index = pending.index
            pending.actions[index] = replace(
                pending.actions[index],
                status=receipt.status,
                detail=receipt.detail,
                data=receipt.data,
            )
            self._pending_action = None
            return self._report(turn_id, pending.actions, pending.tool_call_id)
        except asyncio.CancelledError:
            self.last_result = self._snapshot(
                turn_id, pending.actions, pending.tool_call_id
            )
            raise
        except Exception as error:
            self.last_result = self._snapshot(
                turn_id, pending.actions, pending.tool_call_id
            )
            raise ActionExecutionError(self.last_result) from error

    async def aclose(self, deadline: float) -> Optional[ExecutionResult]:
        """关闭时核对原调用；预算耗尽仅结束本地等待，保留未知事实。"""
        self._closed = True
        pending = self._pending_action
        if pending is None:
            return None
        if not pending.task.done():
            await asyncio.wait(
                {pending.task}, timeout=max(0, deadline - time.monotonic())
            )
        if pending.task.done() and not pending.task.cancelled():
            if self._pending_action is pending:
                return await self.reconcile(pending.turn_id)
            # execute 的原等待者可能已先一步记录回执并结束计划。
            return self.last_result
        pending.task.cancel()
        try:
            await pending.task
        except asyncio.CancelledError:
            pass
        self.last_result = self._report(
            pending.turn_id, pending.actions, pending.tool_call_id
        )
        return self.last_result

    def _snapshot(self, turn_id, outcomes, tool_call_id) -> ExecutionResult:
        """即使报告出错，仍保留设备事实供调用者保存。"""
        return ExecutionResult(
            turn_id,
            "failed",
            "动作执行流程异常，请核对执行记录。",
            tuple(outcomes),
            tool_call_id,
        )

    def _report(self, turn_id, outcomes, tool_call_id) -> ExecutionResult:
        """生成新快照；格式化编程错误由上层携带事实继续抛出。"""
        completed = all(a.status in CONFIRMED_SUCCESS for a in outcomes)
        self.last_result = ExecutionResult(
            turn_id,
            "completed" if completed else "failed",
            confirmed_action_reply(outcomes),
            tuple(outcomes),
            tool_call_id,
        )
        return self.last_result
