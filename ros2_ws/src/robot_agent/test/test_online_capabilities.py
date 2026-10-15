"""通过动作与语音Interface验证能力组装及状态归属。"""

import asyncio
import json

import pytest
from test_online_interaction import FixedProvider

from robot_agent.actions.capabilities import (
    ActionCapabilities,
    create_default_actions,
)
from robot_agent.actions.registry import ActionRegistry
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.provider import DashScopeProvider
from robot_agent.runtime import build_application
from robot_agent.voice.speech import DashScopeTTS


def test_registry_contains_only_explicitly_registered_actions():
    """空注册表不创建默认设备，只处理显式装入的动作契约。"""
    registry = ActionRegistry()
    with pytest.raises(ValueError, match="动作未实现"):
        registry.validate(["head_nod"])
    registry.register("custom", lambda: {"status": "real_success"})
    assert registry.validate(["custom"])[0].name == "custom"
    assert registry.execute("custom", {})["status"] == "real_success"


def test_default_music_state_belongs_to_its_own_capabilities():
    """音乐状态与动作共享同一能力；不同组装之间保持独立。"""
    first, second = create_default_actions(), create_default_actions()
    provider = FixedProvider(["play_music('夜曲')"])
    agent = Agent(provider, first.registry)
    assert not first.music_playing()
    assert asyncio.run(agent.submit("播放"))["status"] == "completed"
    assert first.music_playing()
    assert not second.music_playing()
    provider.functions = ["stop_music"]
    assert asyncio.run(agent.submit("停止"))["status"] == "completed"
    assert not first.music_playing()


def test_voice_filter_uses_injected_music_capability(tmp_path, monkeypatch):
    """替换音乐动作时，语音过滤读取实际注入状态而非隐藏模拟对象。"""
    state = {"playing": False}
    requests = []

    def play():
        """替代音乐Adapter确认播放。"""
        state["playing"] = True
        return {"status": "real_success"}

    def stop():
        """替代音乐Adapter确认停止。"""
        state["playing"] = False
        return {"status": "real_success"}

    def complete(self, text, timeout):
        """仅提供固定模型响应，保留真实交互流程。"""
        requests.append(text)
        if text.startswith("【会话上下文】"):
            text = json.loads(text.split("\n", 1)[1])["current_input"]
        functions = {"播放音乐": ["play_music"], "停止音乐": ["stop_music"]}
        return json.dumps(
            {"function": functions.get(text, []), "response": "好的"}
        )

    def synthesize(self, text, path, timeout):
        """替换合成出口，不访问云端。"""
        path.write_bytes(b"audio fixture")

    registry = ActionRegistry()
    registry.register("play_music", play)
    registry.register("stop_music", stop)
    capabilities = ActionCapabilities(
        registry, music_playing=lambda: state["playing"]
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixed-test-key")
    monkeypatch.setattr(DashScopeProvider, "complete", complete)
    monkeypatch.setattr(DashScopeTTS, "synthesize", synthesize)
    voice = build_application(
        {
            "output_dir": str(tmp_path / "audio"),
            "memory_file": str(tmp_path / "memory.json"),
        },
        capabilities=capabilities,
    )
    try:
        assert (
            asyncio.run(voice.submit_transcript("小莫小莫"))["status"]
            == "woken"
        )
        assert (
            asyncio.run(voice.submit_transcript("播放音乐"))["status"]
            == "completed"
        )
        assert (
            asyncio.run(voice.submit_transcript("今天天气"))["status"]
            == "filtered"
        )
        assert (
            asyncio.run(voice.submit_transcript("停止音乐"))["status"]
            == "completed"
        )
        assert (
            asyncio.run(voice.submit_transcript("今天天气"))["status"]
            == "completed"
        )
        assert len(requests) == 3
    finally:
        asyncio.run(voice.aclose())
