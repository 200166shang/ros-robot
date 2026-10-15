"""本地 HTTPS 替身提供原生工具协议，生产 Adapter 负责全部解析。"""

import io
import json


def native_response(actions=(), response="你好"):
    """提供完整的单计划 SSE 响应，不连接任何模型 endpoint。"""
    delta = {"content": response}
    finish = "stop"
    if actions:
        finish = "tool_calls"
        delta["tool_calls"] = [
            {
                "index": 0,
                "id": "fixture_call",
                "type": "function",
                "function": {
                    "name": "execute_actions",
                    "arguments": json.dumps({"actions": actions}),
                },
            }
        ]
    events = [
        {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
    ]
    wire = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
    return io.BytesIO((wire + "data: [DONE]\n\n").encode())


def install_async_transport(monkeypatch, send):
    """仅替换外部 HTTP 传输，生产请求、流式解码与关闭保持真实。"""
    import httpx

    client_type = httpx.AsyncClient

    async def handler(request):
        """沿用协议 fixture 的明确响应字节。"""
        timeout = request.extensions["timeout"]["read"]
        response = send(request, timeout)
        return httpx.Response(200, content=response.getvalue())

    def client():
        """测试客户端不读取机器代理设置。"""
        return client_type(
            transport=httpx.MockTransport(handler), trust_env=False
        )

    monkeypatch.setattr(
        "robot_agent.conversation.provider.httpx.AsyncClient", client
    )
