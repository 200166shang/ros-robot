"""Replaceable audio-input adapters for the half-duplex voice frontend."""

import shutil
import wave
from pathlib import Path

from .audio_io import record_wav


class MicrophoneAudioSource:
    """Capture one turn from the configured ALSA microphone device."""

    def __init__(self, executable, device, seconds):
        self._executable = executable
        self._device = device
        self._seconds = int(seconds)

    def capture(self, destination):
        return record_wav(
            self._executable, self._device, self._seconds, destination
        )


class WavFileAudioSource:
    """Replay a validated fixture WAV by copying it into the turn temp folder."""

    def __init__(self, input_wav_path):
        self._input_wav_path = Path(input_wav_path).expanduser()

    def capture(self, destination):
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
                "input WAV must be non-empty mono PCM16 at 16000 Hz: {}".format(
                    metadata
                )
            )

        destination = Path(destination)
        if self._input_wav_path.resolve() != destination.resolve():
            shutil.copyfile(str(self._input_wav_path), str(destination))
        return metadata


def create_audio_source(
    mode,
    input_wav_path="",
    record_executable="arecord",
    record_device="plughw:2,0",
    record_seconds=8,
):
    """Create the requested input adapter; microphone remains the default."""
    if mode == "microphone":
        return MicrophoneAudioSource(
            record_executable, record_device, record_seconds
        )
    if mode == "wav_file":
        if not input_wav_path:
            raise ValueError("input_wav_path is required for wav_file mode")
        return WavFileAudioSource(input_wav_path)
    raise ValueError("unsupported audio source: {}".format(mode))
