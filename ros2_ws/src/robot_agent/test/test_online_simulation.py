"""固定模型响应经交互输入验证完整模拟状态与结果。"""

import asyncio
import json

import pytest

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.conversation.agent import Agent


class FixedProvider:
    """每轮提供操作者指定的固定动作建议。"""

    def __init__(self) -> None:
        """初始化无动作响应。"""
        self.functions = []

    def complete(self, text: str, timeout: float) -> str:
        """按旧 function/response 契约返回完整建议。"""
        return json.dumps({"function": self.functions, "response": "建议"})


def submit(agent, provider, *functions):
    """从文本入口提交一轮固定模型建议。"""
    provider.functions = list(functions)
    return asyncio.run(agent.submit("执行指定业务"))


def test_navigation_registration_goal_cancel_and_unknown_failure():
    """位置可在同轮注册后使用，取消可观察，未知目标不能伪报成功。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent,
        provider,
        "add_location('书房', 1, 2)",
        "list_locations",
        "go_to('书房')",
        "navigation_status",
        "cancel_navigation",
        "navigation_status",
    )
    assert result.status == "completed"
    actions = result.actions
    assert actions[1].data["locations"]["书房"] == {
        "x": 1,
        "y": 2,
        "z": 0,
        "qx": 0,
        "qy": 0,
        "qz": 0,
        "qw": 1,
    }
    assert actions[3].data["state"] == "active"
    assert actions[3].data["current_goal"] == "书房"
    assert actions[5].data["state"] == "cancelled"
    assert "书房" in result.reply
    failed = submit(agent, provider, "navigate_to('未知')", "head_smile")
    assert [a.status for a in failed.actions] == [
        "failed",
        "not_executed",
    ]


def test_music_queue_alias_recommendation_and_filter_state():
    """播放别名、队列重复、推荐切歌与停止状态可从回复观察。"""
    provider = FixedProvider()
    registry = create_default_actions().registry
    agent = Agent(provider, registry)
    result = submit(
        agent,
        provider,
        "play_song('小幸运')",
        "add_to_queue('夜曲')",
        "add_to_queue('夜曲')",
        "next_song",
        "music_status",
        "next_song",
        "music_status",
        "recommend_songs('青花瓷')",
    )
    assert result.status == "completed"
    assert result.actions[4].data == {
        "is_playing": True,
        "current_song": "夜曲",
        "queue": ("夜曲",),
    }
    assert result.actions[6].data["queue"] == ()
    assert result.actions[7].data["songs"] == (
        "小幸运",
        "稻香",
        "夜曲",
        "东风破",
    )
    fallback = submit(agent, provider, "next_song", "music_status")
    assert fallback.actions[1].data["current_song"] == "小幸运"
    stopped = submit(agent, provider, "stop_music", "music_status")
    assert stopped.actions[1].data["is_playing"] is False
    assert "夜曲" in result.reply


def test_head_pose_expression_sequence_and_repetition():
    """头部参数保留未指定轴，组合姿态按序展开，LCD保留源映射。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent,
        provider,
        "head_position(pitch=70, yaw=110)",
        "head_down",
        "head_think(2)",
        "head_breathing(cycles=2, duration=0.5)",
        "head_breathing(cycles=2, duration=0.5)",
        "sleep",
        "wake_up",
    )
    assert result.status == "completed"
    actions = result.actions
    assert actions[1].data["pitch"] == 65
    assert actions[1].data["yaw"] == 110
    assert actions[2].data["steps"][0] == {
        "pitch": 80,
        "yaw": 90,
        "duration": 2 / 6,
    }
    assert actions[2].data["pitch"] == 90
    breathing = actions[3].data["steps"]
    assert [s["pitch"] for s in breathing] == [92, 88, 92, 88, 90]
    assert actions[4].data["steps"] == breathing
    assert actions[5].data["display"] == "good_night"
    assert actions[6].data["display"] == "苏醒"


def test_volume_wifi_and_music_display_state():
    """音量饱和、静音及WiFi查询完整模拟，音乐同步LCD但不播放音频。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent,
        provider,
        "volume_set(98)",
        "volume_up",
        "volume_mute",
        "volume_status",
        "volume_down(20)",
        "volume_unmute",
        "volume_status",
        "show_wifi_info",
        "get_wifi_ip",
        "wifi_status",
        "play_music('稻香')",
        "head_position(yaw=90)",
        "stop_music",
        "head_position(yaw=90)",
    )
    assert result.status == "completed"
    assert result.actions[3].data == {"level": 100, "is_muted": True}
    assert result.actions[6].data == {"level": 80, "is_muted": False}
    assert result.actions[7].data["ssid"] == "simulated-network"
    assert result.actions[8].data["ip"] == "192.0.2.2"
    assert result.actions[9].data["connected"] is True
    assert result.actions[11].data["display"] == "兴奋"
    assert result.actions[13].data["display"] == "正常"


# 独立来源为首票动作清单，不能从实现的注册表生成期望覆盖范围。
SIMULATION_CALLS = [
    "head_smile",
    "head_nod",
    "head_shake",
    "head_dance",
    "excited",
    "normal",
    "sleep",
    "wake_up",
    "volume_up",
    "volume_down",
    "volume_set",
    "volume_mute",
    "volume_unmute",
    "volume_status",
    "head_forward",
    "head_down",
    "head_up",
    "head_left",
    "head_right",
    "head_reset",
    "head_position(pitch=90)",
    "show_wifi_info",
    "get_wifi_ip",
    "wifi_status",
    "play_music('小幸运')",
    "play_song('青花瓷')",
    "stop_music",
    "next_song",
    "add_to_queue('夜曲')",
    "music_status",
    "recommend_songs",
    "navigate_to('厨房')",
    "cancel_navigation",
    "go_to('厨房')",
    "navigation_status",
    "list_locations",
    "add_location('客厅', 0, 1)",
    "head_think",
    "head_confused",
    "head_surprised",
    "head_look_around",
    "head_greet",
    "head_goodbye",
    "head_refuse",
    "head_breathing",
    "head_attention",
    "head_emotional",
    "head_listen",
    "head_interest",
    "head_concern",
    "head_agree",
    "head_disagree",
]


def test_every_source_simulation_action_from_interaction():
    """全部52项动作及别名经固定模型入口执行并产生状态，感知留待65票。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(agent, provider, *SIMULATION_CALLS)
    assert result.status == "completed"
    assert len(result.actions) == 52
    for action, call in zip(result.actions, SIMULATION_CALLS):
        assert action.name == call.split("(")[0]
        assert action.status == "simulated_success"
        assert action.data
        assert "模拟" in action.detail
    assert result.actions[37].parameters == {"duration": 2.0}
    assert result.actions[44].parameters == {
        "cycles": 5,
        "duration": 0.5,
    }
    assert result.actions[45].parameters == {
        "direction": "center",
        "duration": 1.0,
    }
    assert result.actions[46].parameters == {
        "emotion": "happy",
        "duration": 3.0,
    }


def test_invalid_parameters_reject_all_without_state_changes():
    """每类错误在全表校验时拒绝，之前的合法修改也不能执行。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    invalid_calls = [
        "head_position()",
        "head_position(64)",
        "head_position(yaw=131)",
        "head_position(True)",
        "head_think(0)",
        "head_greet('慢')",
        "head_breathing(0)",
        "head_breathing(65)",
        "head_breathing(1.5)",
        "head_attention('behind')",
        "head_emotional('unknown')",
        "volume_up(-1)",
        "volume_down('5')",
        "volume_set(True)",
        "play_music('')",
        "add_to_queue(1)",
        "recommend_songs('')",
        "navigate_to('')",
        "add_location('', 0, 0)",
        "add_location('坏姿态', 0, 0, qw=0)",
        "add_location('坏坐标', 'x', 0)",
        "add_location('无穷', 1e309, 0)",
        "head_think(1e309)",
        "wifi_status(1)",
        "volume_mute(level=0)",
    ]
    for invalid in invalid_calls:
        result = submit(agent, provider, "volume_set(90)", invalid)
        assert result.status == "rejected", invalid
        assert result.actions == (), invalid
        query = submit(agent, provider, "volume_status")
        assert query.actions[0].data["level"] == 50, invalid


def test_navigation_overlap_cancel_restart_and_independent_agents():
    """活动目标不得覆盖，取消可重复，位置与播放状态不能跨实例泄漏。"""
    provider = FixedProvider()
    first = Agent(provider, create_default_actions().registry)
    result = submit(
        first, provider, "go_to('厨房')", "navigate_to('厨房')", "head_smile"
    )
    assert [a.status for a in result.actions] == [
        "simulated_success",
        "failed",
        "not_executed",
    ]
    cancelled = submit(
        first, provider, "cancel_navigation", "cancel_navigation"
    )
    assert cancelled.status == "completed"
    restarted = submit(first, provider, "navigate_to('厨房')")
    assert restarted.actions[0].data["state"] == "active"
    submit(first, provider, "add_location('私有', 1, 1)", "play_music('夜曲')")
    second = Agent(provider, create_default_actions().registry)
    result = submit(
        second, provider, "list_locations", "music_status", "navigation_status"
    )
    assert list(result.actions[0].data["locations"]) == ["厨房"]
    assert result.actions[1].data["is_playing"] is False
    assert result.actions[2].data["state"] == "idle"


@pytest.mark.parametrize(
    "direction,pitch,yaw",
    [
        ("left", 90, 130),
        ("right", 90, 50),
        ("up", 120, 90),
        ("down", 65, 90),
        ("center", 90, 90),
    ],
)
def test_attention_direction_parameters(direction, pitch, yaw):
    """五个方向通过关键字参数改变首步姿态，结束回到中心。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent, provider, f"head_attention(direction='{direction}', duration=4)"
    )
    assert result.status == "completed"
    data = result.actions[0].data
    assert data["steps"][0] == {"pitch": pitch, "yaw": yaw, "duration": 2}
    assert (data["pitch"], data["yaw"]) == (90, 90)


@pytest.mark.parametrize(
    "emotion,pitch,yaw",
    [
        ("happy", 65, 90),
        ("sad", 85, 90),
        ("angry", 90, 80),
        ("excited", 65, 90),
        ("calm", 92, 90),
    ],
)
def test_emotional_combinations(emotion, pitch, yaw):
    """五种情感展开不同源组合，时间参数绑定到完整虚拟序列。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent, provider, f"head_emotional(emotion='{emotion}', duration=4)"
    )
    assert result.status == "completed"
    data = result.actions[0].data
    assert data["duration"] == 4
    assert data["steps"][0]["pitch"] == pitch
    assert data["steps"][0]["yaw"] == yaw
    assert (data["pitch"], data["yaw"]) == (90, 90)


def test_full_pose_parameters_and_volume_saturation():
    """完整位置参数与两类别名按位置/关键字形式绑定同一契约。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent,
        provider,
        "add_location(name='客厅', x=-2, y=3, z=1, "
        "qx=0, qy=0, qz=0.6, qw=0.8)",
        "navigate_to(location='客厅')",
        "cancel_navigation",
        "go_to('客厅')",
        "play_music(song_name='夜曲')",
        "play_song('夜曲')",
        "volume_set(200)",
        "volume_down(step=120)",
        "volume_set(-10)",
    )
    assert result.status == "completed"
    assert result.actions[0].data["locations"]["客厅"] == {
        "x": -2,
        "y": 3,
        "z": 1,
        "qx": 0,
        "qy": 0,
        "qz": 0.6,
        "qw": 0.8,
    }
    assert result.actions[1].data == result.actions[3].data
    assert result.actions[4].data == result.actions[5].data
    assert [a.data["level"] for a in result.actions[6:]] == [100, 0, 0]
