"""轻量动作注册表：整表校验，代表模拟动作，其余能力明确拒绝。"""

import ast
import inspect
from typing import Callable, Dict, List, Optional, Tuple


class ActionRegistry:
    """把动作契约与可替换的设备执行函数集中管理。"""

    def __init__(self) -> None:
        """仅注册本票可验收的表情模拟，不接触硬件。"""
        self._entries = {}
        for name in ("head_nod", "head_smile", "head_shake"):
            self.register(name, self._simulate_expression)

    def register(self, name: str, execute: Callable, validate: Optional[Callable] = None) -> None:
        """在设备 Seam 注册执行函数与无副作用参数校验函数。"""
        self._entries[name] = (execute, validate)

    def validate(self, functions: List[str]) -> List[Tuple[str, Dict]]:
        """先解析完整列表，拒绝未知动作、可执行表达式及不合法参数。"""
        if not isinstance(functions, list) or len(functions) > 64:
            raise ValueError("动作列表无效或超过64项")
        commands = []
        for source in functions:
            if not isinstance(source, str) or len(source) > 2048:
                raise ValueError("动作必须是有限长度字符串")
            expression = ast.parse(source, mode="eval").body
            if isinstance(expression, ast.Name):
                name, args, kwargs = expression.id, [], {}
            elif isinstance(expression, ast.Call) and isinstance(expression.func, ast.Name):
                name = expression.func.id
                args = [ast.literal_eval(arg) for arg in expression.args]
                kwargs = {}
                for keyword in expression.keywords:
                    if keyword.arg is None or keyword.arg in kwargs:
                        raise ValueError("不支持展开或重复参数")
                    kwargs[keyword.arg] = ast.literal_eval(keyword.value)
            else:
                raise ValueError("动作只能是函数名称或字面量参数调用")

            if name not in self._entries:
                raise ValueError("动作未实现：" + name)
            execute, validate = self._entries[name]
            bound = inspect.signature(execute).bind(*args, **kwargs)
            bound.apply_defaults()
            if validate is not None:
                validate(**bound.arguments)
            commands.append((name, dict(bound.arguments)))
        return commands

    def execute(self, name: str, parameters: Dict) -> Dict:
        """执行一项已校验动作；状态必须来自 Adapter 的明确回执。"""
        result = self._entries[name][0](**parameters)
        if not isinstance(result, dict) or result.get("status") not in {
            "simulated_success",
            "real_success",
            "failed",
            "unknown",
        }:
            return {"status": "unknown", "detail": "Adapter 未返回有效回执"}
        return result

    @staticmethod
    def _simulate_expression() -> Dict:
        """确认完成日志模拟，不表示物理动作已发生。"""
        return {"status": "simulated_success", "detail": "表情动作仅模拟，无硬件输出"}
