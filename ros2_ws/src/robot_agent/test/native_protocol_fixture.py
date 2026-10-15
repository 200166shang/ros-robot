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
