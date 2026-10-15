"""持续PCM麦克风 Adapter：读取原始帧、清理积压并回收录音进程。"""

import os
import select
import subprocess
import threading
from typing import Optional


class PcmMicrophone:
    """固定单声道PCM16/16kHz；暂停期间由调用者持续读取并丢弃。"""

    def __init__(self, executable: str, device: str) -> None:
        """保存外部录音命令，不在构造时打开设备。"""
        self._args = [
            executable,
            "-q",
            "-D",
            device,
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            "16000",
            "-c",
            "1",
        ]
        self._process: Optional[subprocess.Popen] = None
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._buffer = bytearray()

    def start(self) -> None:
        """启动一个持续采集进程；关闭与启动共享资源所有权。"""
        with self._lock:
            if self._closed.is_set():
                raise OSError("麦克风已关闭")
            self._process = subprocess.Popen(
                self._args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )

    def read(self, size: int, timeout: float = 0.2) -> Optional[bytes]:
        """读取完整PCM帧；短轮询无数据返回None，设备退出明确失败。"""
        process = self._process
        assert process is not None and process.stdout is not None
        try:
            ready, _, _ = select.select([process.stdout], [], [], timeout)
            if not ready:
                return None
            data = os.read(process.stdout.fileno(), size - len(self._buffer))
        except (OSError, ValueError):
            if self._closed.is_set():
                return None
            raise
        if not data:
            if self._closed.is_set():
                return None
            raise OSError("麦克风PCM输入已结束")
        self._buffer.extend(data)
        if len(self._buffer) < size:
            return None
        frame = bytes(self._buffer)
        self._buffer.clear()
        return frame

    def discard(self) -> None:
        """由唯一读取线程清理恢复前的部分帧与管道积压。"""
        self._buffer.clear()
        process = self._process
        assert process is not None and process.stdout is not None
        while not self._closed.is_set():
            try:
                ready, _, _ = select.select([process.stdout], [], [], 0)
                if not ready:
                    return
                data = os.read(process.stdout.fileno(), 65536)
            except (OSError, ValueError):
                if self._closed.is_set():
                    return
                raise
            if not data:
                raise OSError("麦克风PCM输入已结束")

    def close(self) -> None:
        """取消阻塞采集并有界回收子进程。"""
        self._closed.set()
        with self._lock:
            process = self._process
            if process is None:
                return
            try:
                if process.poll() is None:
                    try:
                        process.terminate()
                    finally:
                        try:
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
            finally:
                if process.stdout is not None:
                    process.stdout.close()
