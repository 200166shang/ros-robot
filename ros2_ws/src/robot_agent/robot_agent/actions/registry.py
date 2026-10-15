"""单一目录导出原生工具 Schema，整表绑定后才允许调用设备。"""

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Type

from pydantic import Field
from typing_extensions import Annotated

from robot_agent.actions.contracts import (
    ActionHandler,
    ActionInput,
    NoArguments,
)
from robot_agent.results import ActionReceipt, _freeze, _json_value

CONFIRMED_SUCCESS = frozenset({"simulated_success", "real_success"})
DEVICE_OUTCOMES = CONFIRMED_SUCCESS | {"failed", "unknown"}
MAX_ACTIONS = 64


class RequestedAction(ActionInput):
    """尚未绑定的单项名称和对象参数。"""

    name: str
    arguments: Dict[str, Any]


class RequestedPlan(ActionInput):
    """原生工具必须携带完整且有界的有序动作列表。"""

    actions: Annotated[
        List[RequestedAction], Field(min_length=1, max_length=MAX_ACTIONS)
    ]


@dataclass(frozen=True)
class ActionCommand:
    """输入校验完成后的动作与不可变参数快照。"""

    name: str
    parameters: Mapping[str, Any]

    def __post_init__(self) -> None:
        """复制参数，调用者不能在执行前改写计划。"""
        object.__setattr__(self, "parameters", _freeze(self.parameters))


@dataclass(frozen=True)
class ActionPlan:
    """已完整绑定的计划，保留原顺序和有意重复。"""

    commands: Tuple[ActionCommand, ...]


class ActionRegistry:
    """Schema、默认值绑定、业务校验和实现查找共享同一目录。"""

    def __init__(self) -> None:
        """创建空目录，能力在组装时注册。"""
        self._handlers: Dict[str, ActionHandler] = {}

    def register(
        self,
        name: str,
        execute: Callable,
        validate: Optional[Callable] = None,
        inputs: Type[ActionInput] = NoArguments,
        *,
        timed: bool = False,
    ) -> None:
        """配置明确输入模型；不从带内部参数的执行签名推导 Schema。"""
        self._handlers[name] = ActionHandler(execute, validate, inputs, timed)

    def register_many(self, handlers: Mapping[str, ActionHandler]) -> None:
        """配置阶段批量加载或替换能力。"""
        self._handlers.update(handlers)

    @property
    def tool_schema(self) -> Dict[str, Any]:
        """按目录顺序导出一个携带完整计划的原生工具。"""
        branches = []
        for name, handler in self._handlers.items():
            branches.append(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "arguments"],
                    "properties": {
                        "name": {"type": "string", "const": name},
                        "arguments": handler.inputs.model_json_schema(),
                    },
                }
            )
        return {
            "type": "function",
            "function": {
                "name": "execute_actions",
                "description": "完整有序计划；整表校验，失败或未知停止。",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["actions"],
                    "properties": {
                        "actions": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": MAX_ACTIONS,
                            "items": {"oneOf": branches},
                        }
                    },
                },
            },
        }

    def bind_plan(self, request: Mapping[str, Any]) -> ActionPlan:
        """整表参数和业务校验无副作用；任何失败都不返回可执行计划。"""
        requested = RequestedPlan.model_validate(_json_value(request))
        commands = []
        for item in requested.actions:
            handler = self._handlers.get(item.name)
            if handler is None:
                raise ValueError("动作未实现：" + item.name)
            parameters = handler.inputs.model_validate(
                item.arguments
            ).model_dump()
            if handler.validate is not None:
                handler.validate(**parameters)
            commands.append(ActionCommand(item.name, parameters))
        return ActionPlan(tuple(commands))

    async def invoke(
        self, command: ActionCommand, deadline: float
    ) -> ActionReceipt:
        """直接等待异步设备；即时模拟在当前循环返回，不引入工作线程。"""
        handler = self._handlers[command.name]
        if handler.timed:
            receipt = handler.execute(
                **_json_value(command.parameters), deadline=deadline
            )
        else:
            receipt = handler.execute(**_json_value(command.parameters))
        if inspect.isawaitable(receipt):
            receipt = await receipt
        if isinstance(receipt, ActionReceipt):
            return receipt
        if (
            not isinstance(receipt, dict)
            or receipt.get("status") not in DEVICE_OUTCOMES
        ):
            return ActionReceipt("unknown", "Adapter 未返回有效回执")
        return ActionReceipt(
            receipt["status"], receipt.get("detail", ""), receipt.get("data")
        )
