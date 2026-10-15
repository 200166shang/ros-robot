"""在线交互共同组装：读取外部配置，集中解释依赖和默认值。"""

import json
from pathlib import Path
from typing import Dict, Optional, Union

from .online_actions import ActionRegistry
from .online_interaction import OnlineInteraction
from .online_memory import ConversationMemory
from .online_provider import DashScopeProvider

DEFAULT_ACTION_TIMEOUT = 5.0


def load_config(filename: Union[str, Path]) -> Dict:
    """读取源码外JSON对象；文件、语法和形状错误直接向调用者显露。"""
    config = json.loads(
        Path(filename).expanduser().read_text(encoding="utf-8")
    )
    if not isinstance(config, dict):
        raise ValueError("在线配置必须是JSON对象")
    return config


def create_interaction(
    config: Dict, actions: Optional[ActionRegistry] = None
) -> OnlineInteraction:
    """组装同一交互Implementation；文本测试直接调用，无ROS文本入口。"""
    if actions is None:
        actions = ActionRegistry()
    return OnlineInteraction(
        DashScopeProvider(config),
        actions,
        provider_timeout=float(config.get("provider_timeout", 60)),
        action_timeout=float(
            config.get("action_timeout", DEFAULT_ACTION_TIMEOUT)
        ),
        memory=ConversationMemory(
            Path(
                config.get(
                    "memory_file",
                    "~/.local/state/ros-robot/conversation-summary.json",
                )
            ),
            recent_turns=config.get("memory_recent_turns", 6),
            summary_trigger=config.get("memory_summary_trigger", 6),
        ),
    )
