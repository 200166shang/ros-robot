"""DashScope 兼容 HTTP Adapter，凭证仅从环境读取。"""

import json
import os
import urllib.request
from importlib import resources
from pathlib import Path
from typing import Iterable, Protocol, Union

DEFAULT_ENDPOINT = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
MAX_SSE_LINE_BYTES = 64 * 1024


class TextProvider(Protocol):
    """完整字符串与增量片段共享同一 provider Interface。"""

    def complete(self, text: str, timeout: float) -> Union[str, Iterable[str]]:
        """生成旧 function/response JSON，不执行模型建议的动作。"""
        ...


class DashScopeProvider:
    """在线模型 Adapter：流式传输，业务只消费完整列表。"""

    def __init__(self, config: dict) -> None:
        """加载非敏感外部配置，禁止明文凭证配置与非 HTTPS 端点。"""
        if "api_key" in config:
            raise ValueError("配置使用 api_key_env，不允许明文 api_key")
        self._key = os.environ[config.get("api_key_env", "DASHSCOPE_API_KEY")]
        self._endpoint = config.get("endpoint", DEFAULT_ENDPOINT)
        if not self._endpoint.startswith("https://"):
            raise ValueError("在线端点必须使用 HTTPS")
        self._model = config.get("model", "qwen-plus")

        # 启动时读取一次；默认资源随包安装，也支持源码外提示词覆盖。
        prompt_file = config.get("system_prompt_file")
        if prompt_file is None:
            self._system_prompt = resources.read_text(
                "robot_agent", "online_system_prompt.txt", encoding="utf-8"
            )
        else:
            self._system_prompt = (
                Path(prompt_file).expanduser().read_text(encoding="utf-8")
            )
        if not self._system_prompt.strip():
            raise ValueError("system prompt 文件不能为空")

    def complete(self, text: str, timeout: float) -> Iterable[str]:
        """请求 SSE 增量输出；无重试，异常由交互模块脱敏处理。"""
        # 1. 把文本与动作契约编码为结构化模型请求。
        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": text},
                ],
                "stream": True,
                "response_format": {"type": "json_object"},
                "enable_thinking": False,
            }
        ).encode("utf-8")

        # 2. 仅在 HTTPS 请求头携带凭证，不记录原始 HTTP 错误。
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={
                "Authorization": "Bearer " + self._key,
                "Content-Type": "application/json",
            },
        )

        # 3. 将 SSE 增量内容交给主链路收齐后统一校验。
        # 本次调用负责释放连接；限制单行大小，避免无限 SSE 数据。
        with urllib.request.urlopen(request, timeout=timeout) as response:
            while True:
                line = response.readline(MAX_SSE_LINE_BYTES + 1)
                if len(line) > MAX_SSE_LINE_BYTES:
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
