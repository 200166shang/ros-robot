from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest

from robot_agent.online_provider import OnlineProvider, load_config


def test_external_configuration_requires_credentials_and_safe_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证外部配置的路径、凭证和 HTTPS 约束。"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    path = tmp_path / "online.json"
    path.write_text(json.dumps({"model": "qwen-plus"}))
    with pytest.raises(ValueError, match="required"):
        OnlineProvider(load_config(path))
    with pytest.raises(ValueError, match="absolute"):
        load_config("relative.json")
    for endpoint in ["http://example.com", "https://secret@example.com"]:
        with pytest.raises(ValueError, match="HTTPS"):
            OnlineProvider({"api_key": "test-token", "endpoint": endpoint})


def test_provider_adapter_sends_online_protocol_and_extracts_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证在线请求格式及模型回复提取。"""
    import robot_agent.online_provider as provider_module

    class Response:
        def __enter__(self) -> "Response":
            """返回测试用 HTTPS 响应上下文。"""
            return self

        def __exit__(self, *args: Any) -> None:
            """结束无外部资源的测试上下文。"""
            pass

        def read(self, size: int) -> bytes:
            """返回固定的在线模型 HTTP 响应。"""
            return b'{"choices":[{"message":{"content":"{\\"function\\":[],\\"response\\":\\"hello\\"}"}}]}'

    class Transport:
        def open(self, request: Request, timeout: float) -> Response:
            """验证 HTTP 请求内容并返回固定响应。"""
            assert isinstance(request.data, bytes)
            payload = json.loads(request.data)
            assert payload["messages"][1] == {"role": "user", "content": "hello"}
            assert "function" in payload["messages"][0]["content"]
            assert payload["response_format"] == {"type": "json_object"}
            assert request.get_header("Authorization") == "Bearer test-token"
            return Response()

    monkeypatch.setattr(provider_module, "build_opener", lambda *handlers: Transport())
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    result = OnlineProvider({"api_key": "test-token"}).complete("hello")
    assert json.loads(result) == {"function": [], "response": "hello"}
