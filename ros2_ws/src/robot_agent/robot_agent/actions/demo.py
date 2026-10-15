"""无需 ROS、云端凭证或硬件的完整模拟演示，输入固定模型响应。"""

import json
from typing import List

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.simulation import simulate_cue
from robot_agent.conversation.interaction import OnlineInteraction


class FixedDemoProvider:
    """演示专用固定模型，不能作为真实在线验收证据。"""

    def __init__(self) -> None:
        """初始化本轮动作建议。"""
        self.functions: List[str] = []

    def complete(self, text: str, timeout: float) -> str:
        """按在线契约返回固定动作列表。"""
        return json.dumps({"function": self.functions, "response": "模拟建议"})


def main() -> None:
    """逐轮展示动作、状态、查询、重复及失败停止，始终保持模拟。"""
    # 1. 固定 provider 只用于演示；缺失设备使用默认模拟注册表。
    provider = FixedDemoProvider()
    agent = OnlineInteraction(provider, create_default_actions().registry)
    print(json.dumps(simulate_cue("startup"), ensure_ascii=False))
    scenarios = [
        (
            "设置头部并两次呼吸后苏醒",
            [
                "head_position(pitch=80, yaw=100)",
                "head_breathing(2)",
                "head_breathing(2)",
                "wake_up",
            ],
        ),
        (
            "注册书房并导航、查询、取消",
            [
                "add_location('书房', 1, 2)",
                "list_locations",
                "go_to('书房')",
                "navigation_status",
                "cancel_navigation",
                "navigation_status",
            ],
        ),
        (
            "播放音乐、队列切歌、推荐与停止",
            [
                "play_song('小幸运')",
                "add_to_queue('夜曲')",
                "next_song",
                "recommend_songs",
                "music_status",
                "stop_music",
                "music_status",
            ],
        ),
        (
            "音量、静音与模拟WiFi显示",
            [
                "volume_set(80)",
                "volume_down",
                "volume_mute",
                "volume_status",
                "volume_unmute",
                "show_wifi_info",
                "get_wifi_ip",
                "wifi_status",
            ],
        ),
        (
            "未知目标失败后不能继续动作",
            [
                "navigate_to('不存在')",
                "head_smile",
            ],
        ),
    ]

    # 2. 始终从交互输入提交，观察可信回执，不调用私有执行器。
    for text, functions in scenarios:
        provider.functions = functions
        result = agent.submit(text)
        print(
            json.dumps({"input": text, "result": result}, ensure_ascii=False)
        )
        if result["status"] == "failed":
            print(json.dumps(simulate_cue("error"), ensure_ascii=False))


if __name__ == "__main__":
    main()
