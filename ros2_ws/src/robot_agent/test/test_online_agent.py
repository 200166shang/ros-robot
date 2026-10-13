from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Union

from robot_agent.online_agent import OnlineAgent, SimulatedDevices


class FixedProvider:
    """依次返回预设的模型响应。"""

    def __init__(self, *outputs: str) -> None:
        self.outputs = iter(outputs)

    def complete(self, text: str) -> str:
        """取下一条固定响应，耗尽时模拟 provider 失败。"""
        return next(self.outputs)


def output(functions: Iterable[str] = (), response: str = "你好，我是小沫。") -> str:
    """构造旧在线 function/response 协议的固定响应。"""
    return json.dumps({"function": list(functions), "response": response}, ensure_ascii=False)


def test_text_dialogue_returns_reply_without_actions() -> None:
    """验证普通对话返回回复且不产生动作。"""
    result = OnlineAgent(FixedProvider(output()), SimulatedDevices()).submit("你好")
    assert result == {"success": True, "response": "你好，我是小沫。", "actions": []}


def test_parameter_alias_duplicate_and_next_turn() -> None:
    """验证参数、别名、同轮去重和跨轮重执行。"""
    agent = OnlineAgent(
        FixedProvider(
            output(["volume_set(30)", "volume_set(30)", "head_left"]),
            output(["volume_status"]),
            output(["head_left"]),
        ),
        SimulatedDevices(),
    )
    first = agent.submit("音量三十，向左看")
    assert len(first["actions"]) == 2
    assert all(a["success"] and a["simulated"] for a in first["actions"])
    assert agent.submit("音量多少")["actions"][0]["result"]["volume"] == 30
    assert agent.submit("再向左看")["actions"][0]["success"]
    alias = OnlineAgent(FixedProvider(output(['play_song("小幸运")'])), SimulatedDevices()).submit("播放")
    assert alias["actions"][0]["result"]["song"] == "小幸运"


def test_different_actions_can_execute_concurrently() -> None:
    """验证不同动作能够并发完成。"""
    import threading

    class ConcurrentDevices:
        def __init__(self) -> None:
            self.ready = threading.Barrier(2)

        def execute(self, name: str, args: List[Union[str, int, float]]) -> Dict[str, Any]:
            """等待两个动作同时到达，验证并发执行的可观察结果。"""
            self.ready.wait(timeout=2)
            return {"success": True, "simulated": True, "result": name}

    result = OnlineAgent(FixedProvider(output(["head_left", "volume_mute"])), ConcurrentDevices()).submit("做两个动作")
    assert result["success"]
    assert {a["result"] for a in result["actions"]} == {"head_left", "volume_mute"}


def test_invalid_unknown_and_unimplemented_actions_never_report_success() -> None:
    """验证无效或未实现动作不能伪报成功。"""
    for call in [
        "unknown",
        "start_following",
        "volume_set(nan)",
        "head_left(1)",
        'volume_set(__import__("os"))',
    ]:
        result = OnlineAgent(FixedProvider(output([call], "已完成。")), SimulatedDevices()).submit("执行")
        assert result["success"] is False
        assert result["actions"][0]["success"] is False
        assert "动作失败" in result["response"]


def test_invalid_protocol_and_network_failure_have_observable_feedback() -> None:
    """验证协议及网络失败提供可观察反馈。"""
    for raw in [
        "bad json",
        '{"fc":[],"res":"你好"}',
        '{"function":[],"response":1}',
        '{"function":[],"function":["head_left"],"response":"你好"}',
    ]:
        result = OnlineAgent(FixedProvider(raw), SimulatedDevices()).submit("你好")
        assert result["error"] == "invalid_output"
        assert result["actions"] == []
    result = OnlineAgent(FixedProvider(), SimulatedDevices()).submit("你好")
    assert result["error"] == "provider_failed"
    assert result["response"]


def test_simulated_music_state_is_observable_in_later_turns() -> None:
    """验证后续轮次能够查询模拟音乐状态。"""
    agent = OnlineAgent(
        FixedProvider(
            output(["play_music(小幸运)"]),
            output(["music_status"]),
            output(["stop_music"]),
            output(["music_status"]),
        ),
        SimulatedDevices(),
    )
    assert agent.submit("播放")["actions"][0]["result"]["song"] == "小幸运"
    assert agent.submit("查询")["actions"][0]["result"]["is_playing"] is True
    assert agent.submit("停止")["actions"][0]["success"]
    assert agent.submit("查询")["actions"][0]["result"]["is_playing"] is False
