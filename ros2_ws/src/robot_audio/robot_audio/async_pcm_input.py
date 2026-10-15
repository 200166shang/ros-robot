"""原生异步PCM采集：只保留一个部分帧，同步切换时排空原始管道。"""

import asyncio
import os
import subprocess
from typing import Optional


class AsyncPcmMicrophone:
    """固定PCM16/16kHz；事件循环独占读取、切换与子进程生命周期。"""

    def __init__(self, executable: str, device: str) -> None:
        """保存命令，构造不打开设备。"""
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
        self._process: Optional[asyncio.subprocess.Process] = None
        self._spawning: Optional[asyncio.Task] = None
        self._closing: Optional[asyncio.Task] = None
        self._fd: Optional[int] = None
        self._buffer = bytearray()
        self._closed = False

    async def start(self) -> None:
        """启动唯一录音进程；启动取消仍由关闭操作回收迟到进程。"""
        if self._closed:
            raise OSError("麦克风已关闭")
        if self._spawning is None:
            self._spawning = asyncio.create_task(self._spawn())
        await asyncio.shield(self._spawning)

    async def _spawn(self) -> None:
        """保留原始非阻塞管道，避免StreamReader隐藏恢复前的积压。"""
        read_fd, write_fd = os.pipe()
        os.set_blocking(read_fd, False)
        self._fd = read_fd
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._args, stdout=write_fd, stderr=subprocess.DEVNULL
            )
        finally:
            os.close(write_fd)

    async def read(self, size: int, timeout: float = 0.2) -> Optional[bytes]:
        """轮询完整帧；部分帧保留至下一次读取或显式丢弃。"""
        assert self._fd is not None
        loop = asyncio.get_running_loop()
        ready = asyncio.Event()
        loop.add_reader(self._fd, ready.set)
        try:
            try:
                await asyncio.wait_for(ready.wait(), timeout)
            except asyncio.TimeoutError:
                return None
            try:
                data = os.read(self._fd, size - len(self._buffer))
            except BlockingIOError:
                # 同步discard可能在可读通知与本次读取之间排空管道。
                return None
            if not data:
                raise OSError("麦克风PCM输入已结束")
            self._buffer.extend(data)
            if len(self._buffer) < size:
                return None
            frame = bytes(self._buffer)
            self._buffer.clear()
            return frame
        finally:
            loop.remove_reader(self._fd)

    def discard(self) -> None:
        """同步排空部分帧与内核管道；没有StreamReader或隐藏音频队列。"""
        self._buffer.clear()
        if self._fd is None:
            return
        while True:
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                return
            if not data:
                raise OSError("麦克风PCM输入已结束")

    async def aclose(self) -> None:
        """有界停止并回收录音；所有等待者共享原始清理操作。"""
        if self._closing is None:
            self._closed = True
            self._closing = asyncio.create_task(self._close())
        await asyncio.shield(self._closing)

    async def _close(self) -> None:
        """启动完成后终止进程，最终总是释放管道描述符。"""
        try:
            if self._spawning is not None:
                await self._spawning
            process = self._process
            if process is not None and process.returncode is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    # EOF可先于子进程观察器回执到达；仍须await回收。
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 1)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
        finally:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
