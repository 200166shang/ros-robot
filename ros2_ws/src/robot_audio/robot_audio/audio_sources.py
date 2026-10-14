"""可替换半双工录音输入，文件与麦克风共享 capture Interface。"""

import shutil
import wave
from pathlib import Path
from typing import Callable, Dict, Optional, Union

from .audio_io import record_wav


class MicrophoneAudioSource:
    """通过指定 ALSA 麦克风采集一轮，可响应退出信号。"""

    def __init__(
        self,
        executable: str,
        device: str,
        seconds: int,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> None:
        """保存设备参数与可选退出信号，不在构造时访问麦克风。"""
        self._executable = executable
        self._device = device
        self._seconds = int(seconds)
        self._cancelled = cancelled

    def capture(self, destination: Union[str, Path]) -> Dict[str, int]:
        """执行单轮录音，退出时终止并回收音频进程。"""
        return record_wav(
            self._executable,
            self._device,
            self._seconds,
            destination,
            cancelled=self._cancelled,
        )


class WavFileAudioSource:
    """将校验后的已有 WAV 复制到单轮临时目录。"""

    def __init__(self, input_wav_path: Union[str, Path]) -> None:
        """保存源录音路径，不修改原录音。"""
        self._input_wav_path = Path(input_wav_path).expanduser()

    def capture(self, destination: Union[str, Path]) -> Dict[str, int]:
        """校验非空单声道16kHz PCM16，再返回原始录音副本。"""
        if not self._input_wav_path.is_file():
            raise FileNotFoundError(
                "input WAV not found: {}".format(self._input_wav_path)
            )

        try:
            with wave.open(str(self._input_wav_path), "rb") as audio:
                metadata = {
                    "frames": audio.getnframes(),
                    "channels": audio.getnchannels(),
                    "sample_rate": audio.getframerate(),
                    "sample_width": audio.getsampwidth(),
                }
        except (OSError, wave.Error) as error:
            raise ValueError("input file is not a readable PCM WAV") from error

        if (
            metadata["frames"] <= 0
            or metadata["channels"] != 1
            or metadata["sample_rate"] != 16000
            or metadata["sample_width"] != 2
        ):
            raise ValueError(
                (
                    "input WAV must be non-empty mono PCM16 at 16000 Hz: {}"
                ).format(metadata)
            )

        destination = Path(destination)
        if self._input_wav_path.resolve() != destination.resolve():
            shutil.copyfile(str(self._input_wav_path), str(destination))
        return metadata


def create_audio_source(
    mode: str,
    input_wav_path: str = "",
    record_executable: str = "arecord",
    record_device: str = "plughw:2,0",
    record_seconds: int = 8,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Union[MicrophoneAudioSource, WavFileAudioSource]:
    """组装指定录音 Adapter；兼容既有默认麦克风入口。"""
    if mode == "microphone":
        return MicrophoneAudioSource(
            record_executable, record_device, record_seconds, cancelled
        )
    if mode == "wav_file":
        if not input_wav_path:
            raise ValueError("input_wav_path is required for wav_file mode")
        return WavFileAudioSource(input_wav_path)
    raise ValueError("unsupported audio source: {}".format(mode))
