"""持续ASR输入：PCM采集、暂停丢弃、静音保活及单句交接。"""

import math
import threading
import time
from concurrent.futures import Future
from typing import Dict, Optional, Protocol

import websocket

from robot_agent.calls import start_call
from robot_agent.voice.speech import (
    FRAME_SAMPLES,
    SILENCE_FRAME,
    SpeechConnection,
)


class PcmInput(Protocol):
    """持续PCM源，读取与清理只有一个调用者，关闭可跨线程取消。"""

    def start(self) -> None:
        """打开采集设备。"""
        ...

    def read(self, size: int, timeout: float = 0.2) -> Optional[bytes]:
        """返回完整帧或轮询无数据；设备失败抛出OSError。"""
        ...

    def discard(self) -> None:
        """清除积压音频，恢复后不得回放暂停期间的录音。"""
        ...

    def close(self) -> None:
        """取消读取并回收设备。"""
        ...


class LiveSpeechInput:
    """一个持续任务、一个最终句槽；业务暂停时不缓存新请求。"""

    def __init__(self, config: Dict, source: PcmInput) -> None:
        """接收PCM Adapter与在线配置，不启动线程或访问麦克风。"""
        self._source = source
        self._connection = SpeechConnection(config)
        self._model = config.get("asr_model", "paraformer-realtime-v2")
        self._attempts = config.get("asr_attempts", 2)
        self._timeout = float(config.get("speech_timeout", 60))
        if type(self._attempts) is not int or self._attempts < 1:
            raise ValueError("asr_attempts 必须为正整数")
        if not math.isfinite(self._timeout) or self._timeout <= 0:
            raise ValueError("speech_timeout 必须为正有限秒数")
        self._connect_timeout = min(self._timeout, 5.0)
        self._condition = threading.Condition()
        self._closed = threading.Event()
        self._paused = False
        self._resume_requested = False
        self._text: Optional[str] = None
        self._stream: Optional[websocket.WebSocket] = None
        self._sent_samples = 0
        self._accept_after_ms = 0
        self._send_error: Optional[Exception] = None
        self._error: Optional[OSError] = None
        self._reader: Optional[Future] = None
        self._receiver: Optional[Future] = None

    def listen(self, timeout: float = 0.2) -> Optional[str]:
        """单调用者领取最终句；无语音返回None，不结束持久ASR任务。"""
        with self._condition:
            if not self._closed.is_set() and self._receiver is None:
                self._source.start()
                self._reader = start_call(self._capture)
                self._receiver = start_call(self._receive)
            self._condition.wait_for(
                lambda: self._text is not None or self._closed.is_set(),
                timeout=timeout,
            )
            text, self._text = self._text, None
        # 资源释放会通知条件，等待Future必须放在条件之外。
        if self._closed.is_set() and self._receiver is not None:
            self._receiver.result(timeout=6)
        if self._error is not None:
            raise self._error
        return text

    def pause(self) -> None:
        """停止真实音频与最终句接入，保留连接并继续读取麦克风。"""
        with self._condition:
            self._paused = True
            self._resume_requested = False

    def resume(self) -> None:
        """请求唯一采集线程清理积压后恢复，不重放旧音频。"""
        with self._condition:
            if not self._closed.is_set():
                self._resume_requested = True

    def _capture(self) -> None:
        """持续消费麦克风；暂停时丢弃源帧并按采样节奏发送静音。"""
        last_frame = time.monotonic()
        while not self._closed.is_set():
            frame = self._source.read(len(SILENCE_FRAME))
            if self._closed.is_set():
                return
            if frame is None:
                if time.monotonic() - last_frame >= self._timeout:
                    raise OSError("麦克风PCM采集超时")
                continue
            last_frame = time.monotonic()
            with self._condition:
                if self._resume_requested:
                    self._source.discard()
                    self._accept_after_ms = self._sent_samples // 16
                    self._resume_requested = False
                    self._paused = False
                    continue
                stream = self._stream
                if stream is None:
                    continue
                try:
                    stream.send_binary(
                        SILENCE_FRAME if self._paused else frame
                    )
                    self._sent_samples += FRAME_SAMPLES
                except (OSError, websocket.WebSocketException) as error:
                    self._send_error = error
                    self._stream = None

    def _receive(self) -> None:
        """持续接收并有界重连；不重放音频、不重复交付暂停期间的句子。"""
        failures = 0
        try:
            while not self._closed.is_set():
                try:
                    stream = self._connection.open(
                        {
                            "task_group": "audio",
                            "task": "asr",
                            "function": "recognition",
                            "model": self._model,
                            "parameters": {
                                "format": "pcm",
                                "sample_rate": 16000,
                                "heartbeat": True,
                            },
                            "input": {},
                        },
                        time.monotonic() + self._connect_timeout,
                    )
                    with self._condition:
                        self._stream = stream
                        self._sent_samples = 0
                        self._accept_after_ms = 0
                        self._send_error = None
                    while not self._closed.is_set():
                        reader = self._reader
                        assert reader is not None
                        if reader.done():
                            reader.result()
                        with self._condition:
                            if self._send_error is not None:
                                raise OSError(
                                    "ASR音频发送失败"
                                ) from self._send_error
                        event = self._connection.receive(stream, math.inf)
                        if event is None or isinstance(event, bytes):
                            continue
                        kind = event["header"]["event"]
                        if kind == "task-finished":
                            raise OSError("持续ASR任务已结束")
                        if kind == "result-generated" and self._accept(event):
                            failures = 0
                except (OSError, websocket.WebSocketException) as error:
                    if self._closed.is_set():
                        return
                    reader = self._reader
                    if reader is not None and reader.done():
                        reader.result()
                    failures += 1
                    if failures >= self._attempts:
                        raise OSError("持续ASR失败，重连次数已耗尽") from error
                finally:
                    with self._condition:
                        self._stream = None
                    self._connection.disconnect()
        except OSError as error:
            self._error = error
        finally:
            self._cancel_io()

    def _cancel_io(self) -> None:
        """任一关闭失败也继续释放其余资源，并唤醒业务调用者。"""
        self._closed.set()
        try:
            self._connection.close()
        finally:
            try:
                self._source.close()
            finally:
                with self._condition:
                    self._condition.notify_all()

    def _accept(self, event: Dict) -> bool:
        """只交付完整非心跳句；时间戳排除暂停期间及恢复前迟到结果。"""
        try:
            sentence = event["payload"]["output"]["sentence"]
            if not sentence["sentence_end"] or sentence.get("heartbeat"):
                return False
            text, begin = sentence["text"], sentence["begin_time"]
            if (
                not isinstance(text, str)
                or type(begin) is not int
                or begin < 0
            ):
                raise ValueError("最终句字段无效")
        except (KeyError, TypeError, ValueError) as error:
            raise OSError("ASR最终句无效") from error
        with self._condition:
            if (
                self._paused
                or begin < self._accept_after_ms
                or not text.strip()
            ):
                return False
            self._paused = True
            self._text = text
            self._condition.notify_all()
            return True

    @staticmethod
    def _join_call(call: Optional[Future]) -> None:
        """回收传输线程；取消I/O可失败，编程异常继续显露。"""
        if call is not None:
            try:
                call.result(timeout=6)
            except (OSError, websocket.WebSocketException):
                pass

    def close(self) -> None:
        """所有关闭和等待步骤均执行，编程异常在资源回收后显露。"""
        try:
            self._cancel_io()
        finally:
            try:
                self._join_call(self._reader)
            finally:
                self._join_call(self._receiver)
