"""ALSA subprocess adapters; replaceable independently from ASR, TTS, and ROS."""

import subprocess
import wave
from pathlib import Path


def _run(args, timeout_seconds, operation):
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("{} timed out".format(operation)) from error

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        raise RuntimeError(
            "{} failed with exit code {}: {}".format(
                operation, completed.returncode, detail
            )
        )
    return completed


def record_wav(
    executable,
    device,
    seconds,
    destination,
    sample_rate=16000,
    timeout_margin_seconds=15,
):
    """Record one mono PCM16 clip through arecord and validate its WAV header."""
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
    _run(args, seconds + timeout_margin_seconds, "microphone recording")

    try:
        with wave.open(str(destination), "rb") as audio:
            metadata = {
                "frames": audio.getnframes(),
                "channels": audio.getnchannels(),
                "sample_rate": audio.getframerate(),
                "sample_width": audio.getsampwidth(),
            }
    except (OSError, wave.Error) as error:
        raise RuntimeError("arecord did not produce a readable WAV file") from error

    if (
        metadata["frames"] <= 0
        or metadata["channels"] != 1
        or metadata["sample_rate"] != sample_rate
        or metadata["sample_width"] != 2
    ):
        raise RuntimeError("recorded WAV has an unexpected format: {}".format(metadata))
    return metadata


def play_wav(executable, device, wav_path, timeout_margin_seconds=15):
    """Send a WAV to an ALSA playback device; this cannot verify audible sound."""
    try:
        with wave.open(str(wav_path), "rb") as audio:
            duration = audio.getnframes() / float(audio.getframerate())
    except (OSError, wave.Error, ZeroDivisionError) as error:
        raise RuntimeError("TTS did not produce a readable WAV file") from error

    _run(
        [executable, "-D", device, str(wav_path)],
        duration + timeout_margin_seconds,
        "ALSA playback",
    )
    return duration
