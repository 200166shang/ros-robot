"""DashScope 原生工具 Adapter：拥有完整响应和 SSE 片段收集。"""

import asyncio
import io
import json
import os
import time
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import httpx

from robot_agent.results import ModelReply, ToolCall

DEFAULT_ENDPOINT = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
MAX_MODEL_OUTPUT_BYTES = 64 * 1024
MAX_SSE_LINE_BYTES = MAX_MODEL_OUTPUT_BYTES


class ModelProtocolError(ValueError):
    """模型响应不满足完整聊天或单一动作计划协议。"""


def _unique_object(pairs):
    """外部 JSON 禁止重复键，避免参数含义歧义。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelProtocolError("重复 JSON 键")
        result[key] = value
    return result


def _invalid_constant(value):
    """外部 JSON 不接受 NaN 和 Infinity。"""
    raise ModelProtocolError("非有限 JSON 数字")


def _decode(raw):
    """JSON 解码仅留在传输入口。"""
    return json.loads(
        raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
    )


def _object(value) -> Dict[str, Any]:
    """协议对象在外部入口确认形状，再读取具名字段。"""
    if not isinstance(value, dict):
        raise ModelProtocolError("模型协议字段必须为对象")
    return value


class ModelTransportError(Exception):
    """已分类的外部模型故障，只有明确暂时故障允许有限重试。"""

    def __init__(self, code: str, *, transient: bool = False) -> None:
        """只保留脱敏错误代码和重试分类。"""
        super().__init__(code)
        self.code = code
        self.transient = transient


class Model(Protocol):
    """异步模型 Interface；deadline 是所有等待共用的绝对期限。"""

    async def complete(
        self, text: str, deadline: float, *, tools: Optional[Dict] = None
    ) -> ModelReply:
        """tools 为空时禁用工具，用于只读摘要。"""
        ...

    async def aclose(self) -> None:
        """释放模型连接和本地请求资源。"""
        ...


class DashScopeProvider:
    """原生异步 HTTP Adapter，独占并关闭请求响应和连接池。"""

    def __init__(
        self, config: dict, *, client: Optional[httpx.AsyncClient] = None
    ) -> None:
        """加载非敏感配置，凭证只从环境读取，在线端点必须 HTTPS。"""
        if "api_key" in config:
            raise ValueError("配置使用 api_key_env，不允许明文 api_key")
        self._key = os.environ[config.get("api_key_env", "DASHSCOPE_API_KEY")]
        self._endpoint = config.get("endpoint", DEFAULT_ENDPOINT)
        if not self._endpoint.startswith("https://"):
            raise ValueError("在线端点必须使用 HTTPS")
        self._model = config.get("model", "qwen-plus")
        prompt_file = config.get("system_prompt_file")
        if prompt_file is None:
            self._system_prompt = resources.read_text(
                "robot_agent.conversation",
                "online_system_prompt.txt",
                encoding="utf-8",
            )
        else:
            self._system_prompt = (
                Path(prompt_file).expanduser().read_text(encoding="utf-8")
            )
        if not self._system_prompt.strip():
            raise ValueError("system prompt 文件不能为空")
        self._client = client or httpx.AsyncClient()
        self._requests = set()
        self._cancelling = set()
        self._closed = False

    async def complete(
        self, text: str, deadline: float, *, tools: Optional[Dict] = None
    ) -> ModelReply:
        """完整收齐请求后返回记录；不执行工具，也不请求措辞总结。"""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": text},
            ],
            "stream": True,
            "enable_thinking": False,
            "tool_choice": "auto" if tools is not None else "none",
        }
        if tools is not None:
            payload["tools"] = [tools]
            payload["parallel_tool_calls"] = False
        if self._closed:
            raise ModelTransportError("closed")
        task = asyncio.create_task(
            self._request(payload, deadline, tools is not None)
        )
        self._requests.add(task)
        task.add_done_callback(self._retire_request)
        try:
            done, _ = await asyncio.wait(
                {task}, timeout=max(0.0, deadline - time.monotonic())
            )
            if not done:
                raise ModelTransportError("timeout", transient=True)
            return task.result()
        finally:
            self._cancel_request(task)
            # Agent 与 Adapter 的同一期限可能同时取消；清理只取消一次。
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
            if not task.cancelled():
                task.result()

    def _cancel_request(self, task: asyncio.Task) -> None:
        """不把第二次取消传入正在释放响应的同一原请求。"""
        if not task.done() and task not in self._cancelling:
            self._cancelling.add(task)
            task.cancel()

    def _retire_request(self, task: asyncio.Task) -> None:
        """请求清理结束后才释放强引用，并领取尚未观察的异常。"""
        self._requests.discard(task)
        self._cancelling.discard(task)
        if not task.cancelled():
            task.exception()

    async def _request(self, payload, deadline, tools_enabled) -> ModelReply:
        """只在网络入口分类已知外部故障，不隐藏客户端编程错误。"""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelTransportError("timeout", transient=True)
        try:
            async with self._client.stream(
                "POST",
                self._endpoint,
                json=payload,
                headers={"Authorization": "Bearer " + self._key},
                timeout=remaining,
            ) as response:
                response.raise_for_status()
                raw = bytearray()
                line = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_MODEL_OUTPUT_BYTES:
                        raise ModelProtocolError("模型输出过长")
                    done = False
                    for byte in chunk:
                        line.append(byte)
                        if len(line) > MAX_SSE_LINE_BYTES:
                            raise ModelProtocolError("模型输出过长")
                        if byte == 10:
                            if (
                                line.startswith(b"data:")
                                and line[5:].strip() == b"[DONE]"
                            ):
                                done = True
                            line.clear()
                    if done:
                        break
                try:
                    return self._read_response(io.BytesIO(raw), tools_enabled)
                except (
                    KeyError,
                    TypeError,
                    UnicodeError,
                    json.JSONDecodeError,
                ) as error:
                    raise ModelProtocolError("模型协议无效") from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise ModelTransportError(
                "http_" + str(status),
                transient=status in {408, 429, 500, 502, 503, 504},
            ) from error
        except httpx.TimeoutException as error:
            raise ModelTransportError("timeout", transient=True) from error
        except httpx.NetworkError as error:
            raise ModelTransportError("network", transient=True) from error
        except (httpx.RemoteProtocolError, httpx.DecodingError) as error:
            raise ModelProtocolError("模型传输协议无效") from error
        except (httpx.InvalidURL, httpx.UnsupportedProtocol) as error:
            raise ModelTransportError("configuration") from error

    async def aclose(self) -> None:
        """先结束已拥有的请求，再释放连接池。"""
        self._closed = True
        requests = tuple(self._requests)
        for task in requests:
            self._cancel_request(task)
        try:
            if requests:
                await asyncio.gather(*requests, return_exceptions=True)
        finally:
            await self._client.aclose()

    def _read_response(self, response, tools_enabled: bool) -> ModelReply:
        """兼容完整 JSON 与 SSE，截断、多个调用及未完成响应全部拒绝。"""
        content = ""
        call_id = ""
        name = ""
        arguments = ""
        call_type = ""
        finish = None
        size = 0
        while True:
            line = response.readline(MAX_SSE_LINE_BYTES + 1)
            size += len(line)
            if len(line) > MAX_SSE_LINE_BYTES or size > MAX_MODEL_OUTPUT_BYTES:
                raise ModelProtocolError("模型输出过长")
            if not line:
                raise ModelProtocolError("模型响应未正常结束")
            if line.lstrip().startswith(b"{"):
                raw = line + response.read(MAX_MODEL_OUTPUT_BYTES + 1)
                if len(raw) > MAX_MODEL_OUTPUT_BYTES:
                    raise ModelProtocolError("模型输出过长")
                event = _object(_decode(raw))
                choices = event["choices"]
                if len(choices) != 1:
                    raise ModelProtocolError("模型必须返回一个选择")
                choice = _object(choices[0])
                message = _object(choice["message"])
                calls = message.get("tool_calls", [])
                return self._reply(
                    message.get("content"),
                    calls,
                    choice["finish_reason"],
                    tools_enabled,
                )
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                calls = (
                    [
                        {
                            "id": call_id,
                            "type": call_type,
                            "function": {"name": name, "arguments": arguments},
                        }
                    ]
                    if call_id or name or arguments or call_type
                    else []
                )
                return self._reply(content, calls, finish, tools_enabled)
            event = _object(_decode(data))
            choices = event["choices"]
            # 部分端点在最后发送空 choices 的用量统计。
            if not choices:
                continue
            if len(choices) != 1 or _object(choices[0]).get("index", 0) != 0:
                raise ModelProtocolError("模型必须返回一个选择")
            choice = _object(choices[0])
            delta = _object(choice["delta"])
            if finish is not None:
                raise ModelProtocolError("结束后仍有模型片段")
            fragment = delta.get("content")
            if fragment is not None:
                if not isinstance(fragment, str):
                    raise ModelProtocolError("文字片段无效")
                content += fragment
            fragments = delta.get("tool_calls", [])
            if not isinstance(fragments, list) or len(fragments) > 1:
                raise ModelProtocolError("每轮只允许一个完整计划调用")
            for fragment_call in fragments:
                call = _object(fragment_call)
                if type(call["index"]) is not int or call["index"] != 0:
                    raise ModelProtocolError("每轮只允许一个完整计划调用")
                function = _object(call.get("function", {}))
                if call.get("id"):
                    if call_id:
                        raise ModelProtocolError("多个工具调用标识")
                    call_id = call["id"]
                name += function.get("name", "")
                arguments += function.get("arguments", "")
                if "type" in call:
                    call_type += call["type"]
            finish = choice.get("finish_reason")

    def _reply(self, content, calls, finish, tools_enabled) -> ModelReply:
        """协议完整性先于业务校验；工具参数在这里解码一次。"""
        if content is not None and not isinstance(content, str):
            raise ModelProtocolError("模型文字无效")
        if not isinstance(calls, list) or len(calls) > 1:
            raise ModelProtocolError("每轮只允许一个完整计划调用")
        if calls:
            if not tools_enabled or finish != "tool_calls":
                raise ModelProtocolError("工具调用未完成或已被禁用")
            call = _object(calls[0])
            function = _object(call["function"])
            if (
                call["type"] != "function"
                or function["name"] != "execute_actions"
                or not isinstance(call["id"], str)
                or not call["id"]
            ):
                raise ModelProtocolError("工具名称或标识无效")
            arguments = _decode(function["arguments"])
            if not isinstance(arguments, dict):
                raise ModelProtocolError("工具参数必须为对象")
            return ModelReply(
                content or "",
                ToolCall(call["id"], function["name"], arguments),
            )
        if finish != "stop" or not content or not content.strip():
            raise ModelProtocolError("聊天响应未完成或为空")
        return ModelReply(content)
