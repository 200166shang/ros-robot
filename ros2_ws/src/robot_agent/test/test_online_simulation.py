"""固定模型响应经交互输入验证完整模拟状态与结果。"""

import asyncio

import pytest

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.conversation.agent import Agent
from robot_agent.results import ModelReply, ToolCall


class FixedProvider:
    """每轮提供操作者指定的固定动作建议。"""

    def __init__(self) -> None:
        """初始化无动作响应。"""
        self.actions = []

    async def complete(
        self, text: str, deadline: float, *, tools=None
    ) -> ModelReply:
        """返回完整原生计划。"""
        return ModelReply(
            "建议",
            ToolCall(
                "fixture_call", "execute_actions", {"actions": self.actions}
            )
            if self.actions
            else None,
        )

    async def aclose(self):
        """固定模型没有本地连接资源。"""
        pass


def submit(agent, provider, *functions):
    """从文本入口提交一轮固定模型建议。"""
    provider.actions = list(functions)
    return asyncio.run(agent.submit("执行指定业务"))


def test_navigation_registration_goal_cancel_and_unknown_failure():
    """位置可在同轮注册后使用，取消可观察，未知目标不能伪报成功。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent,
        provider,
        {
            "name": "add_location",
            "arguments": {"name": "书房", "x": 1, "y": 2},
        },
        {"name": "list_locations", "arguments": {}},
        {"name": "go_to", "arguments": {"location": "书房"}},
        {"name": "navigation_status", "arguments": {}},
        {"name": "cancel_navigation", "arguments": {}},
        {"name": "navigation_status", "arguments": {}},
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
    failed = submit(
        agent,
        provider,
        {"name": "navigate_to", "arguments": {"location": "未知"}},
        {"name": "head_smile", "arguments": {}},
    )
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
        {"name": "play_song", "arguments": {"song_name": "小幸运"}},
        {"name": "add_to_queue", "arguments": {"song_name": "夜曲"}},
        {"name": "add_to_queue", "arguments": {"song_name": "夜曲"}},
        {"name": "next_song", "arguments": {}},
        {"name": "music_status", "arguments": {}},
        {"name": "next_song", "arguments": {}},
        {"name": "music_status", "arguments": {}},
        {"name": "recommend_songs", "arguments": {"song_name": "青花瓷"}},
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
    fallback = submit(
        agent,
        provider,
        {"name": "next_song", "arguments": {}},
        {"name": "music_status", "arguments": {}},
    )
    assert fallback.actions[1].data["current_song"] == "小幸运"
    stopped = submit(
        agent,
        provider,
        {"name": "stop_music", "arguments": {}},
        {"name": "music_status", "arguments": {}},
    )
    assert stopped.actions[1].data["is_playing"] is False
    assert "夜曲" in result.reply


def test_head_pose_expression_sequence_and_repetition():
    """头部参数保留未指定轴，组合姿态按序展开，LCD保留源映射。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(
        agent,
        provider,
        {"name": "head_position", "arguments": {"pitch": 70, "yaw": 110}},
        {"name": "head_down", "arguments": {}},
        {"name": "head_think", "arguments": {"duration": 2}},
        {
            "name": "head_breathing",
            "arguments": {"cycles": 2, "duration": 0.5},
        },
        {
            "name": "head_breathing",
            "arguments": {"cycles": 2, "duration": 0.5},
        },
        {"name": "sleep", "arguments": {}},
        {"name": "wake_up", "arguments": {}},
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
        {"name": "volume_set", "arguments": {"level": 98}},
        {"name": "volume_up", "arguments": {}},
        {"name": "volume_mute", "arguments": {}},
        {"name": "volume_status", "arguments": {}},
        {"name": "volume_down", "arguments": {"step": 20}},
        {"name": "volume_unmute", "arguments": {}},
        {"name": "volume_status", "arguments": {}},
        {"name": "show_wifi_info", "arguments": {}},
        {"name": "get_wifi_ip", "arguments": {}},
        {"name": "wifi_status", "arguments": {}},
        {"name": "play_music", "arguments": {"song_name": "稻香"}},
        {"name": "head_position", "arguments": {"yaw": 90}},
        {"name": "stop_music", "arguments": {}},
        {"name": "head_position", "arguments": {"yaw": 90}},
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
    {"name": "head_smile", "arguments": {}},
    {"name": "head_nod", "arguments": {}},
    {"name": "head_shake", "arguments": {}},
    {"name": "head_dance", "arguments": {}},
    {"name": "excited", "arguments": {}},
    {"name": "normal", "arguments": {}},
    {"name": "sleep", "arguments": {}},
    {"name": "wake_up", "arguments": {}},
    {"name": "volume_up", "arguments": {}},
    {"name": "volume_down", "arguments": {}},
    {"name": "volume_set", "arguments": {}},
    {"name": "volume_mute", "arguments": {}},
    {"name": "volume_unmute", "arguments": {}},
    {"name": "volume_status", "arguments": {}},
    {"name": "head_forward", "arguments": {}},
    {"name": "head_down", "arguments": {}},
    {"name": "head_up", "arguments": {}},
    {"name": "head_left", "arguments": {}},
    {"name": "head_right", "arguments": {}},
    {"name": "head_reset", "arguments": {}},
    {"name": "head_position", "arguments": {"pitch": 90}},
    {"name": "show_wifi_info", "arguments": {}},
    {"name": "get_wifi_ip", "arguments": {}},
    {"name": "wifi_status", "arguments": {}},
    {"name": "play_music", "arguments": {"song_name": "小幸运"}},
    {"name": "play_song", "arguments": {"song_name": "青花瓷"}},
    {"name": "stop_music", "arguments": {}},
    {"name": "next_song", "arguments": {}},
    {"name": "add_to_queue", "arguments": {"song_name": "夜曲"}},
    {"name": "music_status", "arguments": {}},
    {"name": "recommend_songs", "arguments": {}},
    {"name": "navigate_to", "arguments": {"location": "厨房"}},
    {"name": "cancel_navigation", "arguments": {}},
    {"name": "go_to", "arguments": {"location": "厨房"}},
    {"name": "navigation_status", "arguments": {}},
    {"name": "list_locations", "arguments": {}},
    {"name": "add_location", "arguments": {"name": "客厅", "x": 0, "y": 1}},
    {"name": "head_think", "arguments": {}},
    {"name": "head_confused", "arguments": {}},
    {"name": "head_surprised", "arguments": {}},
    {"name": "head_look_around", "arguments": {}},
    {"name": "head_greet", "arguments": {}},
    {"name": "head_goodbye", "arguments": {}},
    {"name": "head_refuse", "arguments": {}},
    {"name": "head_breathing", "arguments": {}},
    {"name": "head_attention", "arguments": {}},
    {"name": "head_emotional", "arguments": {}},
    {"name": "head_listen", "arguments": {}},
    {"name": "head_interest", "arguments": {}},
    {"name": "head_concern", "arguments": {}},
    {"name": "head_agree", "arguments": {}},
    {"name": "head_disagree", "arguments": {}},
]


def test_every_source_simulation_action_from_interaction():
    """全部52项动作及别名经固定模型入口执行并产生状态，感知留待65票。"""
    provider = FixedProvider()
    agent = Agent(provider, create_default_actions().registry)
    result = submit(agent, provider, *SIMULATION_CALLS)
    assert result.status == "completed"
    assert len(result.actions) == 52
    for action, call in zip(result.actions, SIMULATION_CALLS):
        assert action.name == call["name"]
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
        {"name": "head_position", "arguments": {}},
        {"name": "head_position", "arguments": {"pitch": 64}},
        {"name": "head_position", "arguments": {"yaw": 131}},
        {"name": "head_position", "arguments": {"pitch": True}},
        {"name": "head_think", "arguments": {"duration": 0}},
        {"name": "head_greet", "arguments": {"duration": "慢"}},
        {"name": "head_breathing", "arguments": {"cycles": 0}},
        {"name": "head_breathing", "arguments": {"cycles": 65}},
        {"name": "head_breathing", "arguments": {"cycles": 1.5}},
        {"name": "head_attention", "arguments": {"direction": "behind"}},
        {"name": "head_emotional", "arguments": {"emotion": "unknown"}},
        {"name": "volume_up", "arguments": {"step": -1}},
        {"name": "volume_down", "arguments": {"step": "5"}},
        {"name": "volume_set", "arguments": {"level": True}},
        {"name": "play_music", "arguments": {"song_name": ""}},
        {"name": "add_to_queue", "arguments": {"song_name": 1}},
        {"name": "recommend_songs", "arguments": {"song_name": ""}},
        {"name": "navigate_to", "arguments": {"location": ""}},
        {"name": "add_location", "arguments": {"name": "", "x": 0, "y": 0}},
        {
            "name": "add_location",
            "arguments": {"name": "坏姿态", "x": 0, "y": 0, "qw": 0},
        },
        {
            "name": "add_location",
            "arguments": {"name": "坏坐标", "x": "x", "y": 0},
        },
        {
            "name": "add_location",
            "arguments": {"name": "无穷", "x": float("inf"), "y": 0},
        },
        {"name": "head_think", "arguments": {"duration": float("inf")}},
        {"name": "wifi_status", "arguments": {"unexpected_0": 1}},
        {"name": "volume_mute", "arguments": {"level": 0}},
    ]
    for invalid in invalid_calls:
        result = submit(
            agent,
            provider,
            {"name": "volume_set", "arguments": {"level": 90}},
            invalid,
        )
        assert result.status == "rejected", invalid
        assert result.actions == (), invalid
        query = submit(
            agent, provider, {"name": "volume_status", "arguments": {}}
        )
        assert query.actions[0].data["level"] == 50, invalid


def test_navigation_overlap_cancel_restart_and_independent_agents():
    """活动目标不得覆盖，取消可重复，位置与播放状态不能跨实例泄漏。"""
    provider = FixedProvider()
    first = Agent(provider, create_default_actions().registry)
    result = submit(
        first,
        provider,
        {"name": "go_to", "arguments": {"location": "厨房"}},
        {"name": "navigate_to", "arguments": {"location": "厨房"}},
        {"name": "head_smile", "arguments": {}},
    )
    assert [a.status for a in result.actions] == [
        "simulated_success",
        "failed",
        "not_executed",
    ]
    cancelled = submit(
        first,
        provider,
        {"name": "cancel_navigation", "arguments": {}},
        {"name": "cancel_navigation", "arguments": {}},
    )
    assert cancelled.status == "completed"
    restarted = submit(
        first,
        provider,
        {"name": "navigate_to", "arguments": {"location": "厨房"}},
    )
    assert restarted.actions[0].data["state"] == "active"
    submit(
        first,
        provider,
        {
            "name": "add_location",
            "arguments": {"name": "私有", "x": 1, "y": 1},
        },
        {"name": "play_music", "arguments": {"song_name": "夜曲"}},
    )
    second = Agent(provider, create_default_actions().registry)
    result = submit(
        second,
        provider,
        {"name": "list_locations", "arguments": {}},
        {"name": "music_status", "arguments": {}},
        {"name": "navigation_status", "arguments": {}},
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
        agent,
        provider,
        {
            "name": "head_attention",
            "arguments": {"direction": direction, "duration": 4},
        },
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
        agent,
        provider,
        {
            "name": "head_emotional",
            "arguments": {"emotion": emotion, "duration": 4},
        },
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
        {
            "name": "add_location",
            "arguments": {
                "name": "客厅",
                "x": -2,
                "y": 3,
                "z": 1,
                "qx": 0,
                "qy": 0,
                "qz": 0.6,
                "qw": 0.8,
            },
        },
        {"name": "navigate_to", "arguments": {"location": "客厅"}},
        {"name": "cancel_navigation", "arguments": {}},
        {"name": "go_to", "arguments": {"location": "客厅"}},
        {"name": "play_music", "arguments": {"song_name": "夜曲"}},
        {"name": "play_song", "arguments": {"song_name": "夜曲"}},
        {"name": "volume_set", "arguments": {"level": 200}},
        {"name": "volume_down", "arguments": {"step": 120}},
        {"name": "volume_set", "arguments": {"level": -10}},
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
