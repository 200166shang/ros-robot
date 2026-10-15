"""能力目录和动作注册表共享的执行、校验与截止时间契约。"""

import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Dict, Optional

ACTION_DEADLINE: ContextVar[Optional[float]] = ContextVar(
    "online_action_deadline", default=None
)


@dataclass(frozen=True)
class ActionHandler:
    """设备执行与无副作用参数校验组成同一个动作契约。"""

    execute: Callable[..., Dict]
    validate: Optional[Callable[..., None]] = None


def action_deadline(timeout: float) -> float:
    """复用交互层绝对期限；直接调用设备 Interface 时使用配置期限。"""
    deadline = ACTION_DEADLINE.get()
    return deadline if deadline is not None else time.monotonic() + timeout
