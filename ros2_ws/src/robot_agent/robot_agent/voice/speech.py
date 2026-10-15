"""原生异步WAV识别与TTS，复用严格握手和连接所有权。"""

import asyncio
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional

from robot_agent.voice._async_speech_task import (
    AsyncSpeechConnection,
    AsyncSpeechTask,
    SpeechProtocolError,
    SpeechTransportError,
)

FRAME_SECONDS = 0.1
FRAME_SAMPLES = 1600
SILENCE_FRAME = bytes(FRAME_SAMPLES * 2)


class DashScopeASR:
    """单次文件识别；临时网络失败才以新任务重发完整录音。"""

    def __init__(self, config: Dict) -> None:
        """构造不连接网络，连续输入使用独立的LiveSpeechInput。"""
        self._connection = AsyncSpeechConnection(config)
        self._model = config.get("asr_model", "paraformer-realtime-v2")
        self._attempts = config.get("asr_attempts", 2)
        if type(self._attempts) is not int or self._attempts < 1:
            raise ValueError("asr_attempts 必须为正整数")
        self._paused = False
        self._closed = False
        self._active: Optional[asyncio.Task] = None

    async def recognize(self, path: Path, timeout: float) -> str:
        """先验证外部WAV，再在共享总期限内识别；取消释放所有本地任务。"""
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getframerate(),
            ) != (1, 2, 16000):
                raise ValueError("WAV 必须为单声道 PCM16 16kHz")
            if audio.getnframes() == 0:
                raise ValueError("WAV 不能为空")
        if self._closed:
            raise SpeechTransportError("语音入口已关闭")
        deadline = time.monotonic() + timeout
        operation = asyncio.create_task(self._recognize(path, deadline))
        self._active = operation
        try:
            return await asyncio.wait_for(operation, timeout)
        except asyncio.TimeoutError as error:
            raise SpeechTransportError("在线识别超时") from error
        finally:
            self._active = None

    async def _recognize(self, path: Path, deadline: float) -> str:
        """每轮句子独立，永久协议错误不自动重试。"""
        for attempt in range(self._attempts):
            try:
                return await self._attempt(path, deadline)
            except SpeechTransportError:
                if (
                    attempt + 1 == self._attempts
                    or self._closed
                    or time.monotonic() >= deadline
                ):
                    raise
        raise AssertionError("识别尝试应返回或抛出异常")

    async def _attempt(self, path: Path, deadline: float) -> str:
        """发送与接收并行；发送失败立即结束等待而非滞留接收。"""
        sender = receiver = None
        try:
            task = await self._connection.open(
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
                deadline,
            )
            sender = asyncio.create_task(self._send_audio(path, task))
            receiver = asyncio.create_task(self._receive(task))
            done, _ = await asyncio.wait(
                (sender, receiver), return_when=asyncio.FIRST_COMPLETED
            )
            if sender in done:
                await sender
            return await receiver
        finally:
            try:
                await self._connection.disconnect()
            finally:
                for operation in (sender, receiver):
                    if operation is not None and not operation.done():
                        operation.cancel()
                for operation in (sender, receiver):
                    if operation is not None:
                        try:
                            await operation
                        except (asyncio.CancelledError, SpeechTransportError):
                            pass

    async def _send_audio(self, path: Path, task: AsyncSpeechTask) -> None:
        """暂停不消费源文件，只发送静音；各尝试均从文件起点发送。"""
        with wave.open(str(path), "rb") as audio:
            while True:
                frame = (
                    SILENCE_FRAME
                    if self._paused
                    else audio.readframes(FRAME_SAMPLES)
                )
                if not frame:
                    await task.send("finish-task", {"input": {}})
                    return
                await task.send_binary(frame)
                await asyncio.sleep(FRAME_SECONDS)

    async def _receive(self, task: AsyncSpeechTask) -> str:
        """仅接受格式正确的最终句，完整结束后返回本轮识别文本。"""
        sentences: List[str] = []
        while True:
            message = await task.receive()
            if isinstance(message, bytes):
                continue
            kind = message["header"]["event"]
            if kind == "task-finished":
                return "".join(sentences)
            if kind == "result-generated":
                try:
                    sentence = message["payload"]["output"]["sentence"]
                    final = sentence.get("sentence_end", False)
                    heartbeat = sentence.get("heartbeat", False)
                    text = sentence["text"]
                    if (
                        type(final) is not bool
                        or type(heartbeat) is not bool
                        or not isinstance(text, str)
                    ):
                        raise ValueError("识别句字段无效")
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    AttributeError,
                ) as error:
                    raise SpeechProtocolError("识别事件无效") from error
                if final and not heartbeat:
                    sentences.append(text)

    def pause(self) -> None:
        """暂停源文件输入而不消耗录音。"""
        self._paused = True

    def resume(self) -> None:
        """恢复后继续读取本轮文件。"""
        self._paused = False

    async def aclose(self) -> None:
        """停止重试，取消识别并回收连接、发送与接收。"""
        self._closed = True
        active = self._active
        if active is not None:
            active.cancel()
            try:
                await active
            except asyncio.CancelledError:
                pass
        await self._connection.aclose()


class DashScopeTTS:
    """只有匹配任务的完成确认和非空PCM才原子提交WAV。"""

    def __init__(self, config: Dict) -> None:
        """配置合成声音；重试由VoiceOutput单独持有。"""
        self._connection = AsyncSpeechConnection(config)
        self._model = config.get("tts_model", "cosyvoice-v2")
        self._voice = config.get("tts_voice", "longfeifei_v2")
        self._active: Optional[asyncio.Task] = None

    async def synthesize(
        self, text: str, destination: Path, timeout: float
    ) -> None:
        """握手、发送、音频接收共享调用期限，失败清除不完整文件。"""
        operation = asyncio.create_task(
            self._synthesize(text, destination, time.monotonic() + timeout)
        )
        self._active = operation
        try:
            await asyncio.wait_for(operation, timeout)
        except asyncio.TimeoutError as error:
            raise SpeechTransportError("在线合成超时") from error
        finally:
            self._active = None

    async def _synthesize(
        self, text: str, destination: Path, deadline: float
    ) -> None:
        """本次任务拥有临时WAV与连接，取消也完成清理。"""
        temporary = destination.with_suffix(".wav.tmp")
        try:
            task = await self._connection.open(
                {
                    "task_group": "audio",
                    "task": "tts",
                    "function": "SpeechSynthesizer",
                    "model": self._model,
                    "parameters": {
                        "text_type": "PlainText",
                        "voice": self._voice,
                        "format": "pcm",
                        "sample_rate": 16000,
                        "volume": 50,
                        "rate": 1,
                        "pitch": 1,
                    },
                    "input": {},
                },
                deadline,
            )
            await task.send("continue-task", {"input": {"text": text}})
            await task.send("finish-task", {"input": {}})
            frames = 0
            with wave.open(str(temporary), "wb") as audio:
                audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                while True:
                    message = await task.receive()
                    if isinstance(message, bytes):
                        audio.writeframesraw(message)
                        frames += len(message)
                    elif message["header"]["event"] == "task-finished":
                        break
            if frames == 0 or frames % 2:
                raise SpeechProtocolError("合成没有返回完整PCM16音频")
            temporary.replace(destination)
        finally:
            try:
                await self._connection.disconnect()
            finally:
                if temporary.exists():
                    temporary.unlink()

    async def aclose(self) -> None:
        """永久关闭入口，取消合成并等待临时产物清理。"""
        active = self._active
        if active is not None:
            active.cancel()
            try:
                await active
            except asyncio.CancelledError:
                pass
        await self._connection.aclose()
