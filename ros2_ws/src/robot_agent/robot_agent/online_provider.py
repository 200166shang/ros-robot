"""DashScope 兼容 HTTP Adapter，凭证仅从环境读取。"""

import json
import os
import urllib.request
from typing import Iterable, Protocol, Union


class TextProvider(Protocol):
    """完整字符串与增量片段共享同一 provider Interface。"""

    def complete(self, text: str, timeout: float) -> Union[str, Iterable[str]]:
        """生成旧 function/response JSON，不执行模型建议的动作。"""
        ...


class DashScopeProvider:
    """无 SDK 依赖的在线模型 Adapter；传输为流式，业务只消费完整列表。"""

    def __init__(self, config: dict) -> None:
        """加载非敏感外部配置，禁止明文凭证配置与非 HTTPS 端点。"""
        if "api_key" in config:
            raise ValueError("配置使用 api_key_env，不允许明文 api_key")
        self._key = os.environ[config.get("api_key_env", "DASHSCOPE_API_KEY")]
        self._endpoint = config.get(
            "endpoint", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        )
        if not self._endpoint.startswith("https://"):
            raise ValueError("在线端点必须使用 HTTPS")
        self._model = config.get("model", "qwen-plus")
        self._prompt = (
            "你是小沫。只输出 JSON，字段 function 为按序函数字符串列表，"
            "response 为中文回复。普通聊天 function 必须为空。"
            "当前仅实现 head_nod、head_smile、head_shake 无参数模拟动作。"
            "用户要求其他动作时保留真实函数名，系统会明确拒绝，不得替换成成功模拟。"
            "支持的其他旧动作见用户要求，不得编造执行结果。"
        )

    def complete(self, text: str, timeout: float) -> Iterable[str]:
        """请求 SSE 增量输出；无重试，异常由交互模块脱敏处理。"""
        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": self._prompt},
                    {"role": "user", "content": text},
                ],
                "stream": True,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json"},
        )
        # 连接归属本次调用，结束或异常时释放；限制单行避免无限 SSE 数据。
        with urllib.request.urlopen(request, timeout=timeout) as response:
            while True:
                line = response.readline(65537)
                if len(line) > 65536:
                    raise ValueError("SSE 数据过长")
                if not line:
                    raise ValueError("SSE 未正常结束")
                if not line.startswith(b"data:"):
                    continue
                data = line[5:].strip()
                if data == b"[DONE]":
                    return
                event = json.loads(data)
                for choice in event.get("choices", []):
                    content = choice.get("delta", {}).get("content")
                    if content:
                        yield content
