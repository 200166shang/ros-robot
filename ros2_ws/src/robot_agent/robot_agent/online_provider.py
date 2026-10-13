"""DashScope-compatible HTTPS provider; configuration stays outside source."""

from __future__ import annotations

import json
import math
import os
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Any, Dict, Mapping, Optional, Union
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SYSTEM_PROMPT = """你是小沫，严谨温柔的科研AI。使用自然中文回复。
只输出JSON对象，包含function和response两个字段。function是函数调用字符串列表，
response是第一人称回复。普通对话function为空列表。
可用模拟动作：head_smile、head_nod、head_shake、head_dance、excited、normal、sleep、wake_up、
head_forward、head_down、head_up、head_left、head_right、head_reset、
volume_up(step=5)、volume_down(step=5)、volume_set(level=50)、volume_mute、volume_unmute、volume_status、
play_music(song_name)、play_song(song_name)、stop_music、music_status。
例如{"function":["volume_set(30)"],"response":"我会模拟调整音量。"}。
所有设备动作都是模拟，不能声称真实硬件已执行。未列出的动作未实现，不要编造成功。"""


def load_config(path: Union[str, Path]) -> Dict[str, Any]:
    """读取源码之外的 JSON 配置；路径或配置无效时抛出 ValueError。"""
    path = Path(path).expanduser()
    if not path.is_absolute():
        raise ValueError("configuration path must be absolute")
    path = path.resolve()
    # 凭证配置必须留在源码之外，避免误提交。
    if any((parent / ".git").exists() for parent in path.parents):
        raise ValueError("configuration must be outside a source checkout")
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("invalid configuration")
    return config


class OnlineProvider:
    """以外部配置调用在线模型，返回未经业务解析的协议文本。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        key = os.environ.get("DASHSCOPE_API_KEY") or config.get("api_key", "")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("DASHSCOPE_API_KEY or external api_key is required")
        self._key = key
        self._endpoint = config.get(
            "endpoint",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        parsed = urlsplit(self._endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("endpoint must be an HTTPS URL without embedded credentials")
        self._model = config.get("model", "qwen-plus")
        self._timeout = float(config.get("timeout_seconds", 60))
        if not math.isfinite(self._timeout) or not 0 < self._timeout <= 300:
            raise ValueError("timeout_seconds must be between 0 and 300")

    def complete(self, text: str) -> str:
        """发送一轮文本请求；网络或响应错误交由交互 Interface 处理。"""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 1024,
        }
        request = Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._key}",
            },
            method="POST",
        )
        with build_opener(_NoRedirect()).open(request, timeout=self._timeout) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("provider response too large")
        return _completion_text(raw)


def _completion_text(raw: bytes) -> str:
    """从在线 HTTP 响应提取协议文本，格式错误交由请求边界处理。"""
    result = json.loads(raw)
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("missing completion text")
    return content


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, file_pointer: IO[bytes], code: int, message: str, headers: HTTPMessage, new_url: str) -> Optional[Request]:
        """拒绝重定向，防止认证凭证被转发。"""
        return None
