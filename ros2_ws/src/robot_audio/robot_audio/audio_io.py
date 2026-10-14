"""可替换 ALSA 子进程 Adapters，期限或退出信号到达时回收音频资源。"""

import subprocess
import time
import wave
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

AudioPath = Union[str, Path]
Cancellation = Optional[Callable[[], bool]]


def _run(
    args: List[str],
    timeout_seconds: float,
    operation: str,
    cancelled: Cancellation = None,
) -> subprocess.CompletedProcess:
    """执行有界音频命令；退出时终止并回收在途子进程。"""
    if cancelled is not None and cancelled():
        raise RuntimeError("{} cancelled".format(operation))
    deadline = time.monotonic() + timeout_seconds
    # 1. 本次调用拥有音频子进程，所有退出路径都必须回收。
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        while True:
            if cancelled is not None and cancelled():
                process.terminate()
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise RuntimeError("{} cancelled".format(operation))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("{} timed out".format(operation))
            try:
                stdout, stderr = process.communicate(
                    timeout=min(0.1, remaining)
                )
            except subprocess.TimeoutExpired:
                continue
            break
    finally:
        # 2. 超时或意外异常不能遗留 arecord/aplay。
        if process.poll() is None:
            process.kill()
            process.communicate()
    if process.returncode != 0:
        detail = (stderr or stdout or "").strip()[-500:]
        raise RuntimeError(
            "{} failed with exit code {}: {}".format(
                operation, process.returncode, detail
            )
        )
    return subprocess.CompletedProcess(
        args, process.returncode, stdout, stderr
    )


def record_wav(
    executable: str,
    device: str,
    seconds: int,
    destination: AudioPath,
    sample_rate: int = 16000,
    timeout_margin_seconds: int = 15,
    cancelled: Cancellation = None,
) -> Dict[str, int]:
    """采集单声道 PCM16 WAV；配置校验后执行并验证设备产物。"""
    # 1. 输入边缘校验，既有识别模型只接收16kHz录音。
    seconds = int(seconds)
    sample_rate = int(sample_rate)
    if seconds < 1:
        raise ValueError("record duration must be at least one second")
    if sample_rate != 16000:
        raise ValueError("the selected ASR model expects 16000 Hz input")
    destination = Path(destination)
    args = [
        executable,
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        "1",
        "-d",
        str(seconds),
        str(destination),
    ]
    _run(
        args,
        seconds + timeout_margin_seconds,
        "microphone recording",
        cancelled,
    )

    # 2. 设备输出是外部输入，验证格式后交给已有识别 Interface。
    try:
        with wave.open(str(destination), "rb") as audio:
            metadata = {
                "frames": audio.getnframes(),
                "channels": audio.getnchannels(),
                "sample_rate": audio.getframerate(),
                "sample_width": audio.getsampwidth(),
            }
    except (OSError, wave.Error) as error:
        raise RuntimeError(
            "arecord did not produce a readable WAV file"
        ) from error
    if (
        metadata["frames"] <= 0
        or metadata["channels"] != 1
        or metadata["sample_rate"] != sample_rate
        or metadata["sample_width"] != 2
    ):
        raise RuntimeError(
            "recorded WAV has an unexpected format: {}".format(metadata)
        )
    return metadata


def play_wav(
    executable: str,
    device: str,
    wav_path: AudioPath,
    timeout_margin_seconds: int = 15,
    cancelled: Cancellation = None,
) -> float:
    """播放已保存的 WAV，退出可取消；成功只代表进程确认，不证明可闻。"""
    try:
        with wave.open(str(wav_path), "rb") as audio:
            duration = audio.getnframes() / float(audio.getframerate())
    except (OSError, wave.Error, ZeroDivisionError) as error:
        raise RuntimeError(
            "TTS did not produce a readable WAV file"
        ) from error
    _run(
        [executable, "-D", device, str(wav_path)],
        duration + timeout_margin_seconds,
        "ALSA playback",
        cancelled,
    )
    return duration
