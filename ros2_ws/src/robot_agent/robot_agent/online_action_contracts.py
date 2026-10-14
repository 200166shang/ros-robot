"""能力目录和动作注册表共享的执行、校验契约。"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional


@dataclass(frozen=True)
class ActionHandler:
    """设备执行与无副作用参数校验组成同一个动作契约。"""

    execute: Callable[..., Dict]
    validate: Optional[Callable[..., None]] = None
