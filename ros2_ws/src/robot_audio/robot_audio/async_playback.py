"""异步ALSA播放：每次调用拥有子进程并在所有退出路径回收。"""

import asyncio
import time
import wave
from pathlib import Path
from typing import Optional


class AsyncWavPlayer:
    """仅播放完整WAV，成功表示进程确认而不保证设备可闻。"""

    def __init__(
        self, executable: str, device: str, timeout_margin: float = 15
    ) -> None:
        """构造不启动子进程；期限覆盖播放及配置余量。"""
        self._executable = executable
        self._device = device
        self._timeout_margin = timeout_margin
        self._deadline: Optional[float] = None
        self._active: Optional[asyncio.Task] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._closed = False
        self._closing: Optional[asyncio.Task] = None

    async def __call__(self, path: Path) -> None:
        """异步等待播放，取消和超时都终止并回收播放器。"""
        if self._closed:
            raise OSError("播放器已关闭")
        self._active = asyncio.current_task()
        try:
            await self._play(path)
        finally:
            self._active = None

    async def _play(self, path: Path) -> None:
        """原播放操作拥有创建、等待与回收，不留下过期的调用者引用。"""
        try:
            with wave.open(str(path), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
        except (OSError, wave.Error) as error:
            raise OSError("合成音频不是可读WAV") from error
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                self._executable,
                "-D",
                self._device,
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        )
        process: Optional[asyncio.subprocess.Process] = None
        try:
            try:
                started: asyncio.subprocess.Process = await asyncio.shield(
                    spawning
                )
                process = started
                self._process = started
            except asyncio.CancelledError:
                # 重复取消也不能放弃迟到子进程的所有权。
                while not spawning.done():
                    try:
                        await asyncio.shield(spawning)
                    except asyncio.CancelledError:
                        pass
                process = spawning.result()
                self._process = process
                raise
            try:
                code = await asyncio.wait_for(
                    started.wait(), duration + self._timeout_margin
                )
            except asyncio.TimeoutError as error:
                raise OSError("播放超时") from error
            if code != 0:
                raise OSError(f"播放失败，退出码{code}")
        finally:
            if process is not None:
                reaping = asyncio.create_task(self._reap(process))
                interrupted = False
                while not reaping.done():
                    try:
                        await asyncio.shield(reaping)
                    except asyncio.CancelledError:
                        interrupted = True
                reaping.result()
                self._process = None
                if interrupted:
                    raise asyncio.CancelledError

    async def _reap(self, process: asyncio.subprocess.Process) -> None:
        """正常终止后仍等待原子进程；忽略已退出时的信号竞争。"""
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(
                    process.wait(),
                    0.2
                    if self._deadline is None
                    else max(0, self._deadline - time.monotonic()),
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        await process.wait()

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """永久停止播放；关闭期限到达时直接终止当前本地进程。"""
        if self._closing is None:
            self._closed = True
            self._deadline = deadline
            self._closing = asyncio.create_task(self._close(deadline))
        await asyncio.shield(self._closing)

    async def _close(self, deadline: Optional[float]) -> None:
        """并发关闭共享同一个取消与回收操作。"""
        active = self._active
        if active is None or active.done():
            return
        active.cancel()
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        done, _ = await asyncio.wait(
            [active],
            timeout=None
            if deadline is None
            else max(0, deadline - time.monotonic()),
        )
        if not done:
            raise asyncio.TimeoutError("播放进程未在退出期限内回收")
        if not active.cancelled():
            active.result()
