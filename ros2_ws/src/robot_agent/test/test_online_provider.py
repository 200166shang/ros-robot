"""经真实 provider Interface 验证提示词加载与在线请求契约。"""

import io
import json

import pytest

from robot_agent.online_actions import ActionRegistry
from robot_agent.online_interaction import OnlineInteraction
from robot_agent.online_provider import DashScopeProvider


@pytest.fixture
def captured_requests(monkeypatch):
    """替代 HTTPS 传输，保留真实请求构造和提示词加载流程。"""
    requests = []

    def send(request, timeout):
        """替代外部 HTTPS 响应，记录真实请求并返回流式聊天。"""
        requests.append(json.loads(request.data))
        content = json.dumps({"function": [], "response": "你好"})
        event = {"choices": [{"delta": {"content": content}}]}
        return io.BytesIO(
            ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n").encode()
        )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", send)
    return requests


def test_default_prompt_preserves_legacy_contract(captured_requests):
    """请求保留旧人设、格式、动作示例与目录，同时限定当前执行能力。"""
    agent = OnlineInteraction(DashScopeProvider({}), ActionRegistry())
    assert agent.submit("你好")["reply"] == "你好"
    prompt = captured_requests[0]["messages"][0]["content"]
    for required in (
        "用户创造的科研AI",
        "技术精准与情感共鸣",
        "【输出json格式】",
        'play_music("小幸运")',
        "head_position",
        "head_listen",
        "volume_set",
        "start_following",
        "go_to",
        "show_wifi_info",
        "【当前 ROS 2 部署约束】",
        "volume_set(level=50)",
        "真实感知动作：",
        "stop_camera_collection",
    ):
        assert required in prompt


def test_external_prompt_file_overrides_packaged_default(
    tmp_path,
    captured_requests,
):
    """源码外 UTF-8 提示词原样进入 system message，不回退到默认内容。"""
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("定制提示词，保留 JSON 契约。", encoding="utf-8")
    provider = DashScopeProvider({"system_prompt_file": str(prompt_file)})
    agent = OnlineInteraction(provider, ActionRegistry())
    assert agent.submit("你好")["status"] == "completed"
    assert captured_requests[0]["messages"][0]["content"] == (
        "定制提示词，保留 JSON 契约。"
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
