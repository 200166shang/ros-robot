"""动作字符串在输入处解析，注册表负责整表校验与设备调用。"""

import ast
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, NamedTuple, Optional

SIMULATED_EXPRESSIONS = frozenset({"head_nod", "head_smile", "head_shake"})
CONFIRMED_SUCCESS = frozenset({"simulated_success", "real_success"})
DEVICE_OUTCOMES = CONFIRMED_SUCCESS | {"failed", "unknown"}
MAX_ACTIONS = 64
MAX_ACTION_SOURCE_LENGTH = 2048


@dataclass(frozen=True)
class ActionCall:
    """保留输入中的位置参数与关键字参数，尚未绑定设备契约。"""

    name: str
    args: List[Any]
    kwargs: Dict[str, Any]


class ActionCommand(NamedTuple):
    """已校验的动作及绑定参数；保留 validate 原有的元组解包兼容性。"""

    name: str
    parameters: Dict[str, Any]


@dataclass(frozen=True)
class ActionHandler:
    """设备执行与无副作用参数校验组成同一个动作契约。"""

    execute: Callable[..., Dict]
    validate: Optional[Callable[..., None]] = None


def parse_action(source: str) -> ActionCall:
    """只接受函数名称和字面量参数，不执行输入中的 Python 表达式。"""
    if not isinstance(source, str) or len(source) > MAX_ACTION_SOURCE_LENGTH:
        raise ValueError("动作必须是有限长度字符串")

    expression = ast.parse(source, mode="eval").body
    if isinstance(expression, ast.Name):
        return ActionCall(expression.id, [], {})
    if not isinstance(expression, ast.Call) or not isinstance(
        expression.func, ast.Name
    ):
        raise ValueError("动作只能是函数名称或字面量参数调用")

    args = [ast.literal_eval(arg) for arg in expression.args]
    kwargs = {}
    for keyword in expression.keywords:
        if keyword.arg is None or keyword.arg in kwargs:
            raise ValueError("不支持展开或重复参数")
        kwargs[keyword.arg] = ast.literal_eval(keyword.value)
    return ActionCall(expression.func.id, args, kwargs)


def simulate_expression() -> Dict:
    """模拟表情完成，无舵机或显示设备输出。"""
    return {
        "status": "simulated_success",
        "detail": "表情动作仅模拟，无硬件输出",
    }


class ActionRegistry:
    """集中管理动作契约；校验完整列表之后才允许交互模块执行。"""

    def __init__(self) -> None:
        """当前三个无参数表情共用日志模拟，不创建每动作子类。"""
        self._handlers = {
            name: ActionHandler(execute=simulate_expression)
            for name in SIMULATED_EXPRESSIONS
        }

    def register(
        self, name: str, execute: Callable, validate: Optional[Callable] = None
    ) -> None:
        """配置或替换设备契约；不要在回合处理中修改注册表。"""
        self._handlers[name] = ActionHandler(
            execute=execute, validate=validate
        )

    def validate(self, functions: List[str]) -> List[ActionCommand]:
        """全表校验无副作用，任一动作无效则不返回可执行列表。"""
        if not isinstance(functions, list) or len(functions) > MAX_ACTIONS:
            raise ValueError("动作列表无效或超过64项")

        commands = []
        for source in functions:
            call = parse_action(source)
            commands.append(self._validate_action(call))
        return commands

    def _validate_action(self, call: ActionCall) -> ActionCommand:
        """调用形式由设备签名约束，参数含义由设备校验器约束。"""
        handler = self._handlers.get(call.name)
        if handler is None:
            raise ValueError("动作未实现：" + call.name)

        parameters = inspect.signature(handler.execute).bind(
            *call.args, **call.kwargs
        )
        parameters.apply_defaults()
        if handler.validate is not None:
            handler.validate(**parameters.arguments)
        return ActionCommand(call.name, dict(parameters.arguments))

    def execute(self, name: str, parameters: Dict) -> Dict:
        """设备回执在 Adapter 出口确认，内部只消费统一的结果状态。"""
        handler = self._handlers[name]
        receipt = handler.execute(**parameters)
        if (
            not isinstance(receipt, dict)
            or receipt.get("status") not in DEVICE_OUTCOMES
        ):
            return {"status": "unknown", "detail": "Adapter 未返回有效回执"}
        return receipt
