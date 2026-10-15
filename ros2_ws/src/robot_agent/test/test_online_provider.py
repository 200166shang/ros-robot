"""经真实 provider Interface 验证提示词加载与在线请求契约。"""

import asyncio
import json

import pytest
from native_protocol_fixture import native_response

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.provider import DashScopeProvider


@pytest.fixture
def captured_requests(monkeypatch):
    """替代 HTTPS 传输，保留真实请求构造和提示词加载流程。"""
    requests = []

    def send(request, timeout):
        """替代外部 HTTPS 响应，记录真实请求并返回流式聊天。"""
        requests.append(json.loads(request.data))
        return native_response(response="你好")

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", send)
    return requests


def test_default_prompt_uses_native_plan_contract(captured_requests):
    """提示词保留人设与部署语义，目录仅从工具 Schema 导出。"""
    agent = Agent(DashScopeProvider({}), create_default_actions().registry)
    assert asyncio.run(agent.submit("你好")).reply == "你好"
    body = captured_requests[0]
    prompt = body["messages"][0]["content"]
    for required in (
        "用户创造的科研AI",
        "技术精准与情感共鸣",
        "execute_actions",
        "dry-run",
        "【内部会话摘要】",
    ):
        assert required in prompt
    assert body["tools"][0] == create_default_actions().registry.tool_schema
    assert body["tool_choice"] == "auto"
    assert "response_format" not in body


def test_external_prompt_file_overrides_packaged_default(
    tmp_path,
    captured_requests,
):
    """源码外 UTF-8 提示词原样进入 system message，不回退到默认内容。"""
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("定制提示词，遵循原生工具契约。", encoding="utf-8")
    provider = DashScopeProvider({"system_prompt_file": str(prompt_file)})
    agent = Agent(provider, create_default_actions().registry)
    assert asyncio.run(agent.submit("你好")).status == "completed"
    assert captured_requests[0]["messages"][0]["content"] == (
        "定制提示词，遵循原生工具契约。"
    )


@pytest.mark.parametrize("exists", [True, False])
def test_invalid_external_prompt_fails_at_startup(
    tmp_path,
    captured_requests,
    exists,
):
    """空或缺失的外部提示词阻止启动，不能静默换回默认提示词。"""
    prompt_file = tmp_path / "prompt.txt"
    if exists:
        prompt_file.write_text("  \n", encoding="utf-8")
    error = ValueError if exists else FileNotFoundError
    with pytest.raises(error):
        DashScopeProvider({"system_prompt_file": str(prompt_file)})
    assert captured_requests == []


def test_summary_request_disables_native_tools(tmp_path, monkeypatch):
    """摘要使用真实请求构造禁用工具，不为动作回复额外请求模型措辞。"""
    from robot_agent.conversation.memory import ConversationMemory

    requests = []

    def send(request, timeout):
        """先返回原生动作，再返回纯文字摘要。"""
        body = json.loads(request.data)
        requests.append(body)
        if len(requests) == 1:
            return native_response(
                [{"name": "head_nod", "arguments": {}}], "我已完成"
            )
        return native_response(response="只记录模拟 LCD 已确认")

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-key")
    monkeypatch.setattr("urllib.request.urlopen", send)
    agent = Agent(
        DashScopeProvider({}),
        create_default_actions().registry,
        memory=ConversationMemory(tmp_path / "memory.json", 1, 1),
    )
    result = asyncio.run(agent.submit("点头"))
    assert result.status == "completed"
    assert result.memory_warnings == ()
    assert len(requests) == 2
    summary = requests[1]
    assert summary["tool_choice"] == "none"
    assert "tools" not in summary
    assert "【摘要任务】" in summary["messages"][-1]["content"]
    assert result.reply.startswith("head_nod：模拟成功")
