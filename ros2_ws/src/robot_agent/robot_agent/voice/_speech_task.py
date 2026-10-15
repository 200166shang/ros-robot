"""内部语音任务传输：统一鉴权、握手、控制协议与连接生命周期。"""

import json
import os
import threading
import time
import uuid
from typing import Dict, Optional, Union

import websocket

DEFAULT_SPEECH_ENDPOINT = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"


class SpeechTask:
    """单轮协议任务；持有原始连接、任务标识、期限及传输错误转换。"""

    def __init__(
        self,
        connection: websocket.WebSocket,
        deadline: float,
        closed: threading.Event,
    ) -> None:
        """连接由入口创建，任务关闭状态与入口共享。"""
        self._socket = connection
        self._deadline = deadline
        self._closed = closed
        self._task_id = uuid.uuid4().hex

    def send(self, action: str, payload: Dict) -> None:
        """所有控制消息使用本轮唯一标识。"""
        self._check_deadline(self._deadline)
        message = json.dumps(
            {
                "header": {
                    "action": action,
                    "task_id": self._task_id,
                    "streaming": "duplex",
                },
                "payload": payload,
            }
        )
        try:
            self._socket.send(message)
        except websocket.WebSocketException as error:
            raise OSError("在线语音控制消息发送失败") from error

    def send_binary(self, frame: bytes) -> None:
        """发送 PCM 帧；采集循环控制期限，持续 ASR 不沿用握手期限。"""
        self._check_deadline(float("inf"))
        try:
            self._socket.send_binary(frame)
        except websocket.WebSocketException as error:
            raise OSError("在线语音音频发送失败") from error

    def _check_deadline(self, deadline: float) -> None:
        """关闭或超过调用期限时中止传输。"""
        if self._closed.is_set() or time.monotonic() >= deadline:
            raise TimeoutError("语音连接关闭或任务超时")

    def receive(
        self, deadline: Optional[float] = None
    ) -> Optional[Union[Dict, bytes]]:
        """轮询事件；外部协议校验与传输异常都在任务内完成。"""
        self._check_deadline(self._deadline if deadline is None else deadline)
        try:
            message = self._socket.recv()
        except websocket.WebSocketTimeoutException:
            return None
        except websocket.WebSocketException as error:
            raise OSError("在线语音接收失败") from error
        if not message:
            raise OSError("语音连接中断")
        if isinstance(message, bytes):
            return message
        try:
            event = json.loads(message)
            header = event["header"]
            if header["task_id"] != self._task_id:
                raise ValueError("任务标识不匹配")
            if header["event"] == "task-failed":
                raise OSError("在线语音任务失败")
            return event
        except (ValueError, KeyError, TypeError) as error:
            raise OSError("在线语音事件无效") from error

    def disconnect(self) -> None:
        """释放本轮连接，允许入口创建下一轮任务。"""
        try:
            self._socket.close(timeout=0)
        except websocket.WebSocketException as error:
            raise OSError("在线语音连接释放失败") from error


class SpeechConnection:
    """语音任务入口；集中鉴权、握手、取消和连接所有权。"""

    def __init__(self, config: Dict) -> None:
        """环境读取凭证，外部端点必须加密，退出关闭在途连接。"""
        if "api_key" in config:
            raise ValueError("使用 api_key_env，不允许明文 api_key")
        self._key = os.environ[config.get("api_key_env", "DASHSCOPE_API_KEY")]
        self._endpoint = config.get("speech_endpoint", DEFAULT_SPEECH_ENDPOINT)
        if not self._endpoint.startswith("wss://"):
            raise ValueError("语音端点必须使用 WSS")
        self._task: Optional[SpeechTask] = None
        self._lock = threading.Lock()
        self.closed = threading.Event()

    def open(self, payload: Dict, deadline: float) -> SpeechTask:
        """创建任务并完成握手；失败或迟到的连接始终释放。"""
        remaining = deadline - time.monotonic()
        if remaining <= 0 or self.closed.is_set():
            raise TimeoutError("语音任务期限已到或入口已关闭")
        try:
            connection = websocket.create_connection(
                self._endpoint,
                header={"Authorization": "Bearer " + self._key},
                timeout=remaining,
            )
        except websocket.WebSocketException as error:
            raise OSError("在线语音连接失败") from error
        task = SpeechTask(connection, deadline, self.closed)
        with self._lock:
            if self.closed.is_set():
                task.disconnect()
                raise OSError("语音入口已关闭")
            self._task = task
        try:
            connection.settimeout(min(0.2, remaining))
            task.send("run-task", payload)
            while True:
                event = task.receive()
                if event is not None and not isinstance(event, bytes):
                    if event["header"]["event"] == "task-started":
                        return task
        except websocket.WebSocketException as error:
            self.disconnect()
            raise OSError("在线语音握手失败") from error
        except BaseException:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        """释放当前任务，允许下轮重新建立连接。"""
        with self._lock:
            task, self._task = self._task, None
        if task is not None:
            task.disconnect()

    def close(self) -> None:
        """取消入口与在途任务，迟到连接由建立线程回收。"""
        self.closed.set()
        self.disconnect()
