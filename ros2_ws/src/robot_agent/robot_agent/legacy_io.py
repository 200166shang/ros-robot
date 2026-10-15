"""迁移期阻塞 I/O Adapter；调用所有权不暴露给业务调用者。"""

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol

from robot_agent.calls import LegacyCall
from robot_agent.voice.output import VoiceOutput


class SpeechInput(Protocol):
    """旧输入只需生命周期能力，不要求麦克风同时提供文件识别。"""

    def pause(self) -> None:
        """暂停有效音频。"""
        ...

    def resume(self) -> None:
        """恢复有效音频。"""
        ...

    def close(self) -> None:
        """释放输入资源。"""
        ...


class LegacyRecordingInput:
    """只持有独立文件识别操作，不要求实现持续监听。"""

    def __init__(self, recognize: Callable[[Path, float], str]) -> None:
        """接管文件识别能力。"""
        self._recognize = recognize
        self._recording = LegacyCall()

    async def recognize(self, path: Path, timeout: float) -> str:
        """识别文件后把最终文本交给应用。"""
        return await self._recording.run(
            lambda: self._recognize(path, timeout)
        )


class LegacySpeechInput:
    """持有阻塞语音输入的生命周期与持续监听操作。"""

    def __init__(self, source: Any) -> None:
        """接管实际输入 Adapter；文件识别由独立 Adapter 负责。"""
        self._source = source
        self._listen = LegacyCall()
        self._close = LegacyCall()

    async def listen(self, timeout: float = 0.1) -> Optional[str]:
        """等待最终文本；正常空闲超时由旧输入返回 None。"""
        return await self._listen.run(lambda: self._source.listen(timeout))

    def pause(self) -> None:
        """同步切换输入的暂停标记。"""
        self._source.pause()

    def resume(self) -> None:
        """同步恢复有效音频。"""
        self._source.resume()

    async def aclose(self) -> None:
        """关闭原输入以释放监听和采集资源。"""
        await self._close.run(self._source.close)


class LegacyVoiceOutput:
    """持有现有合成/播放/记录 Implementation 及其阻塞操作。"""

    def __init__(self, output: VoiceOutput) -> None:
        """输出资源由此 Adapter 统一接管。"""
        self._output = output
        self._completion = LegacyCall()
        self._close = LegacyCall()

    async def complete(
        self,
        result: Dict,
        text: str,
        session_state: str,
        *,
        reconcile_id: Optional[str] = None,
        input_failed: bool = False,
    ) -> Dict:
        """等待完整语音记录，不重新执行 Agent。"""
        return await self._completion.run(
            lambda: self._output.complete(
                result,
                text,
                session_state,
                reconcile_id=reconcile_id,
                input_failed=input_failed,
            )
        )

    def enable_tts(self) -> None:
        """只在回合间恢复合成。"""
        self._output.enable_tts()

    def cancel(self) -> None:
        """立即禁止输出重试与播放。"""
        self._output.cancel()

    async def aclose(self) -> None:
        """关闭原合成资源并唤醒重试等待。"""
        await self._close.run(self._output.close)
