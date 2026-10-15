"""默认动作能力组装：集中设备关系与语音所需的音乐状态。"""

from dataclasses import dataclass
from typing import Callable

from robot_agent.actions.head_simulation import HeadSimulation, head_actions
from robot_agent.actions.registry import ActionRegistry
from robot_agent.actions.simulation import (
    MusicSimulation,
    NavigationSimulation,
    VolumeSimulation,
    music_actions,
    navigation_actions,
    volume_actions,
    wifi_actions,
)


@dataclass(frozen=True)
class ActionCapabilities:
    """已配置动作与同一音乐能力的状态查询，由入口一起注入。"""

    registry: ActionRegistry
    music_playing: Callable[[], bool]


def create_default_actions() -> ActionCapabilities:
    """组装既有模拟动作；设备共享关系不进入注册表Interface。"""
    # 1. 每次组装持有独立状态；音乐与WiFi共用头部LCD。
    navigation = NavigationSimulation()
    head = HeadSimulation()
    music = MusicSimulation(head.expression)
    volume = VolumeSimulation()
    registry = ActionRegistry()

    # 2. 注册表只接收动作契约，不认识默认设备对象。
    registry.register_many(head_actions(head))
    registry.register_many(navigation_actions(navigation))
    registry.register_many(music_actions(music))
    registry.register_many(volume_actions(volume))
    registry.register_many(wifi_actions(head.expression))
    return ActionCapabilities(registry, music_playing=lambda: music.is_playing)
