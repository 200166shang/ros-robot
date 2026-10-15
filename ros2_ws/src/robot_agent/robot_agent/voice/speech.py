"""DashScope 流式 ASR/TTS Adapters：有界连接、暂停保活和资源释放。"""

import threading
import time
import wave
from concurrent.futures import Future
from pathlib import Path
from typing import Dict, List, Optional

from robot_agent.calls import start_call
from robot_agent.voice._speech_task import SpeechConnection, SpeechTask

FRAME_SECONDS = 0.1
FRAME_SAMPLES = 1600
SILENCE_FRAME = bytes(FRAME_SAMPLES * 2)


class DashScopeASR:
    """按帧发送录音，仅接纳最终识别句；断线有限重连整轮音频。"""

    def __init__(self, config: Dict) -> None:
        """配置真实在线识别模型和有限重连次数。"""
        self._connection = SpeechConnection(config)
        self._model = config.get("asr_model", "paraformer-realtime-v2")
        self._attempts = config.get("asr_attempts", 2)
        if not isinstance(self._attempts, int) or self._attempts < 1:
            raise ValueError("asr_attempts 必须为正整数")
        self._paused = threading.Event()

    def recognize(self, path: Path, timeout: float) -> str:
        """在总期限内完成真实 WAV 识别，重连时不复用失败连接的句子。"""
        # 1. 外部 WAV 格式校验；复用录音入口契约，不转写预知文本。
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getframerate(),
            ) != (1, 2, 16000):
                raise ValueError("WAV 必须为单声道 PCM16 16kHz")
            if audio.getnframes() == 0:
                raise ValueError("WAV 不能为空")
        deadline = time.monotonic() + timeout
        for attempt in range(self._attempts):
            stop = threading.Event()
            sender: Optional[Future] = None
            try:
                # 2. 每次重连使用新任务；采集与最终识别同时进行。
                task = self._connection.open(
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
                sender = start_call(
                    lambda: self._send_audio(path, task, stop, deadline)
                )
                sentences: List[str] = []
                while True:
                    if sender.done():
                        sender.result()
                    event = task.receive(deadline)
                    if event is None or isinstance(event, bytes):
                        continue
                    kind = event["header"]["event"]
                    if kind == "task-finished":
                        return "".join(sentences)
                    if kind == "result-generated":
                        try:
                            sentence = event["payload"]["output"]["sentence"]
                            if sentence.get(
                                "sentence_end"
                            ) and not sentence.get("heartbeat"):
                                text = sentence["text"]
                                if not isinstance(text, str):
                                    raise ValueError("识别文本不是字符串")
                                sentences.append(text)
                        except (KeyError, TypeError, ValueError) as error:
                            raise OSError("识别事件无效") from error
            except OSError as error:
                if (
                    attempt + 1 == self._attempts
                    or time.monotonic() >= deadline
                    or self._connection.closed.is_set()
                ):
                    raise OSError("在线识别失败，有限重连已停止") from error
            finally:
                # 3. 接收失败先停发送，再关闭连接。
                stop.set()
                self._connection.disconnect()
                if sender is not None:
                    try:
                        sender.result(timeout=1)
                    except OSError:
                        pass
        raise OSError("在线识别未完成")

    def _send_audio(
        self,
        path: Path,
        task: SpeechTask,
        stop: threading.Event,
        deadline: float,
    ) -> None:
        """以100毫秒帧发送；暂停不消耗源录音，仅发送静音保活。"""
        with wave.open(str(path), "rb") as audio:
            while not stop.is_set():
                if (
                    self._connection.closed.is_set()
                    or time.monotonic() >= deadline
                ):
                    raise TimeoutError("音频发送已停止")
                frame = (
                    SILENCE_FRAME
                    if self._paused.is_set()
                    else audio.readframes(FRAME_SAMPLES)
                )
                if not frame:
                    task.send("finish-task", {"input": {}})
                    return
                task.send_binary(frame)
                stop.wait(FRAME_SECONDS)

    def pause(self) -> None:
        """暂停有效音频输入；活跃识别由发送循环发送静音保活。"""
        self._paused.set()

    def resume(self) -> None:
        """恢复有效输入，已关闭的单回合连接在下次识别时重新建立。"""
        self._paused.clear()

    def close(self) -> None:
        """停止活跃识别和音频发送，释放在线连接。"""
        self._connection.close()


class DashScopeTTS:
    """接收流式 PCM 音频，最终确认成功才提交 WAV，失败删除临时文件。"""

    def __init__(self, config: Dict) -> None:
        """配置在线声音；播放由外部设备 Adapter 决定。"""
        self._connection = SpeechConnection(config)
        self._model = config.get("tts_model", "cosyvoice-v2")
        self._voice = config.get("tts_voice", "longfeifei_v2")

    def synthesize(self, text: str, destination: Path, timeout: float) -> None:
        """流式保存真实合成音频，整个握手及生成共享同一期限。"""
        deadline = time.monotonic() + timeout
        temporary = destination.with_suffix(".wav.tmp")
        try:
            # 1. 确认任务启动后提交可信文本，再显式结束文本输入。
            task = self._connection.open(
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
            task.send("continue-task", {"input": {"text": text}})
            task.send("finish-task", {"input": {}})
            # 2. 音频片段直接落盘；task-finished 才代表合成成功。
            frames = 0
            with wave.open(str(temporary), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                while True:
                    event = task.receive(deadline)
                    if isinstance(event, bytes):
                        audio.writeframesraw(event)
                        frames += len(event)
                    elif (
                        event is not None
                        and event["header"]["event"] == "task-finished"
                    ):
                        break
            if frames == 0:
                raise OSError("合成没有返回音频")
            temporary.replace(destination)
        finally:
            # 3. 失败产物不冒充音频；连接由本次合成负责释放。
            self._connection.disconnect()
            if temporary.exists():
                temporary.unlink()

    def close(self) -> None:
        """关闭在途合成连接。"""
        self._connection.close()
