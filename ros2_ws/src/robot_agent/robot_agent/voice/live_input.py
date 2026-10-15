"""持续ASR：独立采集、单帧交接、静音保活及单句交付。"""

import asyncio
import math
import time
from typing import Dict, List, Optional, Protocol, Tuple

from robot_agent.shutdown import finish_tasks
from robot_agent.voice._async_speech_task import (
    AsyncSpeechConnection,
    AsyncSpeechTask,
    SpeechProtocolError,
    SpeechTransportError,
)
from robot_agent.voice.speech import FRAME_SAMPLES, SILENCE_FRAME


class PcmInput(Protocol):
    """事件循环独占PCM源；同步discard清理所有音频缓冲。"""

    async def start(self) -> None:
        """打开采集进程。"""
        ...

    async def read(self, size: int, timeout: float = 0.2) -> Optional[bytes]:
        """读取完整帧或返回None；设备失败抛出OSError。"""
        ...

    def discard(self) -> None:
        """同步清理部分帧与源积压。"""
        ...

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """停止并回收采集进程。"""
        ...


class SpeechInput(Protocol):
    """应用直接等待持续输入，暂停标记由同一事件循环同步切换。"""

    async def listen(self, timeout: float = 0.2) -> Optional[str]:
        """返回一个最终句或正常等待超时。"""
        ...

    def pause(self) -> None:
        """暂停有效音频及最终句交付。"""
        ...

    def resume(self) -> None:
        """丢弃旧音频后恢复。"""
        ...

    def stop(self) -> None:
        """同步停止音频、最终句和重连准入。"""
        ...

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """结束所有持有的输入任务和资源。"""
        ...


class LiveSpeechInput:
    """持有采集与网络任务；业务只领取一个最终句，不累积请求。"""

    def __init__(self, config: Dict, source: PcmInput) -> None:
        """构造只保存配置，不启动录音或网络操作。"""
        self._source = source
        self._connection = AsyncSpeechConnection(config)
        self._model = config.get("asr_model", "paraformer-realtime-v2")
        self._attempts = config.get("asr_attempts", 2)
        self._timeout = float(config.get("speech_timeout", 60))
        if type(self._attempts) is not int or self._attempts < 1:
            raise ValueError("asr_attempts 必须为正整数")
        if not math.isfinite(self._timeout) or self._timeout <= 0:
            raise ValueError("speech_timeout 必须为正有限秒数")
        self._closed = False
        self._deadline: Optional[float] = None
        self._paused = False
        self._started = False
        self._text: Optional[str] = None
        self._changed: asyncio.Event
        self._frame_ready: asyncio.Event
        self._restart: asyncio.Event
        self._epoch = 0
        self._frame: Optional[Tuple[int, bytes]] = None
        self._sending = False
        self._sent_samples = 0
        self._accept_after_ms = 0
        self._last_final_begin = -1
        self._failures = 0
        self._runner: Optional[asyncio.Task] = None
        self._closing: Optional[asyncio.Task] = None

    async def listen(self, timeout: float = 0.2) -> Optional[str]:
        """超时只结束本次等待；取消调用则关闭输入，不留下后台资源。"""
        if self._runner is None and self._closed:
            return None
        if self._runner is None:
            self._changed = asyncio.Event()
            self._frame_ready = asyncio.Event()
            self._restart = asyncio.Event()
            self._runner = asyncio.create_task(self._run())
            self._runner.add_done_callback(lambda task: self._changed.set())
        try:
            if self._text is None and not self._closed:
                try:
                    await asyncio.wait_for(self._changed.wait(), timeout)
                except asyncio.TimeoutError:
                    return None
            self._changed.clear()
            if self._runner is not None:
                if self._closed and not self._runner.done():
                    await asyncio.wait([self._runner])
                if self._runner.done():
                    try:
                        self._runner.result()
                    except asyncio.CancelledError:
                        return None
            text, self._text = self._text, None
            return text
        except asyncio.CancelledError:
            await self.aclose()
            raise

    def pause(self) -> None:
        """立即停止交付与真实音频；独立采集仍持续排空设备。"""
        self._paused = True
        self._frame = None
        self._epoch += 1
        if self._sending:
            self._restart.set()

    def resume(self) -> None:
        """同步清理全部缓冲；未完成旧发送必须关闭旧任务后再接入。"""
        if self._closed:
            return
        self._cutover()
        self._accept_after_ms = max(
            self._sent_samples // 16, self._last_final_begin + 1
        )
        self._paused = False
        if self._sending:
            self._restart.set()

    def _cutover(self) -> None:
        """清理源、部分帧和单帧交接槽，失效所有旧读取结果。"""
        self._epoch += 1
        self._frame = None
        if self._started:
            self._frame_ready.clear()
            self._source.discard()

    async def _run(self) -> None:
        """任一采集/网络失败唤醒监听，并在错误显露前释放全部资源。"""
        tasks = []
        try:
            await self._source.start()
            self._started = True
            if self._closed:
                return
            tasks = [
                asyncio.create_task(self._capture()),
                asyncio.create_task(self._network()),
            ]
            done, _ = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                await task
        finally:
            self._closed = True
            try:
                await self._connection.aclose(self._deadline)
            finally:
                try:
                    await self._stop(tasks)
                finally:
                    await self._source.aclose(self._deadline)
                    self._changed.set()

    async def _capture(self) -> None:
        """采集独立于socket背压；最多交接最新一帧，断线和暂停不积压。"""
        last_frame = time.monotonic()
        while not self._closed:
            epoch = self._epoch
            frame = await self._source.read(
                len(SILENCE_FRAME), min(0.2, self._timeout)
            )
            if frame is None:
                if time.monotonic() - last_frame >= self._timeout:
                    raise OSError("麦克风PCM采集超时")
                continue
            last_frame = time.monotonic()
            # 读取完成可能赢过取消；关闭和切换后的帧都不能交给发送者。
            if self._closed or epoch != self._epoch:
                continue
            self._frame = (epoch, SILENCE_FRAME if self._paused else frame)
            self._frame_ready.set()

    async def _network(self) -> None:
        """只有网络失败消耗连续预算；重连成功不重置，最终句才重置。"""
        while not self._closed:
            tasks = []
            try:
                stream = await self._connection.open(
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
                    time.monotonic() + min(self._timeout, 5),
                )
                if self._closed:
                    return
                self._cutover()
                self._sent_samples = 0
                self._accept_after_ms = 0
                self._last_final_begin = -1
                self._restart.clear()
                tasks = [
                    asyncio.create_task(self._send(stream)),
                    asyncio.create_task(self._receive(stream)),
                    asyncio.create_task(self._restart.wait()),
                ]
                done, _ = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    await task
            except SpeechTransportError as error:
                if self._closed:
                    return
                self._failures += 1
                if self._failures >= self._attempts:
                    raise OSError("持续ASR失败，重连次数已耗尽") from error
            finally:
                try:
                    await self._connection.disconnect()
                finally:
                    await self._stop(tasks)
                    self._sending = False

    async def _send(self, stream: AsyncSpeechTask) -> None:
        """唯一socket发送者；采集持续覆盖交接槽，不等待网络发送完成。"""
        while not self._closed:
            await self._frame_ready.wait()
            if self._closed:
                return
            self._frame_ready.clear()
            pending, self._frame = self._frame, None
            if pending is None or pending[0] != self._epoch:
                continue
            self._sending = True
            await stream.send_binary(pending[1])
            self._sent_samples += FRAME_SAMPLES
            self._sending = False

    async def _receive(self, stream: AsyncSpeechTask) -> None:
        """唯一socket接收者；接收循环不承担PCM失败检测。"""
        while not self._closed:
            event = await stream.receive()
            if self._closed:
                return
            if isinstance(event, bytes):
                continue
            kind = event["header"]["event"]
            if kind == "task-finished":
                raise SpeechTransportError("持续ASR任务已结束")
            if kind == "result-generated":
                self._accept(event)

    def _accept(self, event: Dict) -> None:
        """最终句与暂停原子交接，时间戳过滤跨越恢复切换的迟到结果。"""
        try:
            sentence = event["payload"]["output"]["sentence"]
            final = sentence["sentence_end"]
            heartbeat = sentence.get("heartbeat", False)
            if type(final) is not bool or type(heartbeat) is not bool:
                raise ValueError("最终句标志无效")
            if not final or heartbeat:
                return
            text, begin = sentence["text"], sentence["begin_time"]
            if (
                not isinstance(text, str)
                or type(begin) is not int
                or begin < 0
            ):
                raise ValueError("最终句字段无效")
        except (KeyError, TypeError, ValueError) as error:
            raise SpeechProtocolError("ASR最终句无效") from error
        if (
            self._paused
            or self._restart.is_set()
            or begin < self._accept_after_ms
            or not text.strip()
        ):
            return
        self.pause()
        self._text = text
        self._last_final_begin = begin
        self._failures = 0
        self._changed.set()

    @staticmethod
    async def _stop(tasks: List[asyncio.Task]) -> None:
        """回收全部原始任务；取消不掩盖已经完成的编程错误。"""
        for task in tasks:
            if not task.done():
                task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(
                result, OSError
            ):
                raise result

    def stop(self) -> None:
        """第一次等待之前禁止真实音频、旧文本和后续连接。"""
        self._closed = True
        self._text = None
        self._frame = None
        self._epoch += 1
        self._connection.stop()

    async def aclose(self, deadline: Optional[float] = None) -> None:
        """所有关闭调用共享清理任务；编程异常在资源回收后继续显露。"""
        if self._closing is None:
            self.stop()
            self._deadline = deadline
            self._closing = asyncio.create_task(self._close())
        await asyncio.shield(self._closing)

    async def _close(self) -> None:
        """停止采集与网络并行收尾；连接关闭不能延后其他资源回收。"""
        tasks = [asyncio.create_task(self._connection.aclose(self._deadline))]
        if self._runner is not None:
            if not self._runner.done():
                self._runner.cancel()
            tasks.append(asyncio.create_task(self._finish_runner()))
        else:
            tasks.append(
                asyncio.create_task(self._source.aclose(self._deadline))
            )
        try:
            await finish_tasks(tasks, self._deadline)
        finally:
            if self._runner is not None:
                self._changed.set()

    async def _finish_runner(self) -> None:
        """输入故障已经由listen报告，关闭仍传播未分类编程错误。"""
        assert self._runner is not None
        try:
            await self._runner
        except (asyncio.CancelledError, OSError):
            pass
