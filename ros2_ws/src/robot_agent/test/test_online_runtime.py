"""通过共同组装Interface验证配置、文本交互与持久记忆。"""

import asyncio
import json

import pytest
from native_protocol_fixture import install_async_transport, native_response

from robot_agent.actions.registry import ActionRegistry
from robot_agent.runtime import build_agent, load_config


def install_model_transport(monkeypatch):
    """只替换HTTPS出口，保留真实provider与模型输出解析。"""
    requests = []

    def send(request, timeout):
        """记录输入与调用期限，提供符合线上契约的流式响应。"""
        body = json.loads(request.content)
        text = body["messages"][-1]["content"]
        requests.append((text, timeout))
        return native_response(response="记住 recent-marker")

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixed-test-key")
    install_async_transport(monkeypatch, send)
    return requests


def test_loaded_config_drives_text_memory_restart_and_clear(
    tmp_path, monkeypatch
):
    """共同配置驱动真实provider与记忆，文本测试无需ROS节点。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        requests = install_model_transport(monkeypatch)
        config_file = tmp_path / "online.json"
        memory_file = tmp_path / "memory.json"
        config_file.write_text(
            json.dumps(
                {
                    "memory_file": str(memory_file),
                    "memory_recent_turns": 2,
                    "memory_summary_trigger": 2,
                    "provider_timeout": "1.5",
                }
            ),
            encoding="utf-8",
        )
        config = load_config(config_file)
        agent = build_agent(config)
        first = await agent.submit("recent-marker")
        assert first.status == "completed"
        assert not first.memory_warnings
        assert (await agent.submit("继续聊天")).status == "completed"
        assert "recent-marker" in requests[1][0]
        assert memory_file.exists()
        assert all(0 < timeout <= 1.5 for _, timeout in requests)

        restarted = build_agent(config)
        assert (await restarted.submit("重启后")).status == "completed"
        assert "recent-marker" in requests[-1][0]
        assert (await restarted.clear_memory()).status == "completed"
        assert (await restarted.submit("重新聊天")).status == "completed"
        assert requests[-1][0] == "重新聊天"
        await agent.aclose()
        await restarted.aclose()

    asyncio.run(scenario())


def test_config_rejects_non_object_json(tmp_path):
    """外部配置必须为JSON对象，不能把错误形状传入组装流程。"""
    filename = tmp_path / "online.json"
    filename.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON对象"):
        load_config(filename)


def test_invalid_common_settings_fail_before_interaction(
    tmp_path, monkeypatch
):
    """共同组装保留超时和记忆阈值的既有校验契约。"""
    requests = install_model_transport(monkeypatch)
    config = {"memory_file": str(tmp_path / "memory.json")}
    with pytest.raises(ValueError, match="超时"):
        build_agent(dict(config, action_timeout=0))
    with pytest.raises(ValueError, match="记忆回合"):
        build_agent(dict(config, memory_recent_turns=1))
    assert requests == []


def test_custom_actions_are_used_by_common_assembly(tmp_path, monkeypatch):
    """显式动作Adapter原样接入，组装不另建注册表覆盖它。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fixed-test-key")
        executions = []

        def nod():
            """通过公开动作Interface记录执行事实。"""
            executions.append("nod")
            return {"status": "simulated_success", "detail": "测试确认"}

        def send(request, timeout):
            """提供两次相同动作，验证顺序与有意重复均保留。"""
            return native_response(
                [{"name": "head_nod", "arguments": {}}] * 2, "模型承诺"
            )

        install_async_transport(monkeypatch, send)
        actions = ActionRegistry()
        actions.register("head_nod", nod)
        agent = build_agent(
            {"memory_file": str(tmp_path / "memory.json")}, actions
        )
        result = await agent.submit("点头两次")
        assert result.status == "completed"
        assert executions == ["nod", "nod"]
        assert "测试确认" in result.reply
        assert "模型承诺" not in result.reply

    asyncio.run(scenario())
