"""异步ALSA播放：每次调用拥有子进程并在所有退出路径回收。"""

import asyncio
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

    async def __call__(self, path: Path) -> None:
        """异步等待播放，取消和超时都终止并回收播放器。"""
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
                process = await asyncio.shield(spawning)
            except asyncio.CancelledError:
                # 取消等待不放弃迟到子进程的所有权。
                process = await spawning
                raise
            try:
                code = await asyncio.wait_for(
                    process.wait(), duration + self._timeout_margin
                )
            except asyncio.TimeoutError as error:
                raise OSError("播放超时") from error
            if code != 0:
                raise OSError(f"播放失败，退出码{code}")
        finally:
            if process is not None:
                await self._reap(process)

    async def _reap(self, process: asyncio.subprocess.Process) -> None:
        """正常终止后仍等待原子进程；忽略已退出时的信号竞争。"""
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 0.2)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        await process.wait()
