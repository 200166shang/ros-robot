"""原生异步语音任务：鉴权、严格握手、事件校验与连接所有权。"""

import asyncio
import json
import os
import time
import uuid
from typing import Dict, Optional, Union

from websockets.asyncio import client
from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    InvalidStatus,
)

DEFAULT_SPEECH_ENDPOINT = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"


class SpeechTransportError(OSError):
    """可重连的网络断开或连接超时。"""


class SpeechProtocolError(OSError):
    """永久协议、鉴权或服务端任务错误，不自动重试。"""


class AsyncSpeechTask:
    """连接只允许一个发送者与一个接收者，任务持有唯一标识。"""

    def __init__(self, socket: client.ClientConnection) -> None:
        """持有已经打开的原始连接。"""
        self._socket = socket
        self._task_id = uuid.uuid4().hex
        self._closing: Optional[asyncio.Task] = None

    async def send(self, action: str, payload: Dict) -> None:
        """控制消息共享任务标识。"""
        await self._send(
            json.dumps(
                {
                    "header": {
                        "action": action,
                        "task_id": self._task_id,
                        "streaming": "duplex",
                    },
                    "payload": payload,
                }
            )
        )

    async def send_binary(self, frame: bytes) -> None:
        """发送PCM，背压由调用者持有的发送任务等待。"""
        await self._send(frame)

    async def _send(self, message: Union[str, bytes]) -> None:
        """只分类外部网络错误，编程错误原样传播。"""
        try:
            await self._socket.send(message)
        except (ConnectionClosed, OSError) as error:
            raise SpeechTransportError("在线语音发送失败") from error

    async def receive(self) -> Union[Dict, bytes]:
        """读取并验证不可信事件，服务端错误与网络断线分开。"""
        try:
            message = await self._socket.recv()
        except (ConnectionClosed, OSError) as error:
            raise SpeechTransportError("在线语音接收失败") from error
        if isinstance(message, bytes):
            return message
        try:
            event = json.loads(message)
            header = event["header"]
            if header["task_id"] != self._task_id:
                raise ValueError("任务标识不匹配")
            if not isinstance(header["event"], str):
                raise ValueError("事件类型无效")
        except (ValueError, KeyError, TypeError) as error:
            raise SpeechProtocolError("在线语音事件无效") from error
        if header["event"] == "task-failed":
            raise SpeechProtocolError("在线语音任务失败")
        return event

    async def aclose(self) -> None:
        """先关闭socket以解除发送背压，再由持有者回收发送任务。"""
        if self._closing is None:
            self._closing = asyncio.create_task(self._socket.close())
        await asyncio.shield(self._closing)


class AsyncSpeechConnection:
    """调用者持有open操作；入口持有socket并关闭未完成的握手。"""

    def __init__(self, config: Dict) -> None:
        """环境读取凭证，构造不建立网络连接。"""
        if "api_key" in config:
            raise ValueError("使用 api_key_env，不允许明文 api_key")
        self._key = os.environ[config.get("api_key_env", "DASHSCOPE_API_KEY")]
        self._endpoint = config.get("speech_endpoint", DEFAULT_SPEECH_ENDPOINT)
        if not self._endpoint.startswith("wss://"):
            raise ValueError("语音端点必须使用 WSS")
        self._task: Optional[AsyncSpeechTask] = None
        self._closed = False

    async def open(self, payload: Dict, deadline: float) -> AsyncSpeechTask:
        """总期限覆盖连接与握手，失败或取消总是释放已创建的socket。"""
        if self._closed:
            raise SpeechTransportError("语音入口已关闭")
        try:
            return await asyncio.wait_for(
                self._open(payload, deadline),
                max(0, deadline - time.monotonic()),
            )
        except asyncio.TimeoutError as error:
            raise SpeechTransportError("在线语音握手超时") from error

    async def _open(self, payload: Dict, deadline: float) -> AsyncSpeechTask:
        """严格等待task-started，握手前不允许提交音频。"""
        try:
            socket = await client.connect(
                self._endpoint,
                additional_headers={"Authorization": "Bearer " + self._key},
                open_timeout=max(0, deadline - time.monotonic()),
                close_timeout=0.2,
                max_queue=1,
            )
        except InvalidStatus as error:
            if error.response.status_code in (408, 429, 500, 502, 503, 504):
                raise SpeechTransportError("在线语音连接暂不可用") from error
            raise SpeechProtocolError("在线语音鉴权或端点失败") from error
        except InvalidHandshake as error:
            raise SpeechProtocolError("在线语音握手无效") from error
        except (OSError, asyncio.TimeoutError) as error:
            raise SpeechTransportError("在线语音连接失败") from error
        task = AsyncSpeechTask(socket)
        self._task = task
        try:
            if self._closed:
                raise SpeechTransportError("语音入口已关闭")
            await task.send("run-task", payload)
            event = await task.receive()
            if (
                isinstance(event, bytes)
                or event["header"]["event"] != "task-started"
            ):
                raise SpeechProtocolError("在线语音握手事件无效")
            return task
        except BaseException:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        """释放当前任务，允许持续输入创建下一任务。"""
        task = self._task
        if task is not None:
            await task.aclose()
            if self._task is task:
                self._task = None

    async def aclose(self) -> None:
        """永久停止入口并释放当前socket。"""
        self._closed = True
        await self.disconnect()
