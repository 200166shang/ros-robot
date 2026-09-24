"""Sherpa-ONNX CLI adapter for the bilingual streaming Zipformer model."""

import json
import subprocess
from pathlib import Path


def extract_transcript(output):
    """Read the last non-empty structured transcript emitted by sherpa-onnx."""
    decoder = json.JSONDecoder()
    transcripts = []
    cursor = 0

    while cursor < len(output):
        start = output.find("{", cursor)
        if start < 0:
            break
        try:
            payload, consumed = decoder.raw_decode(output[start:])
        except (TypeError, ValueError):
            cursor = start + 1
            continue

        if isinstance(payload, dict) and isinstance(payload.get("text"), str):
            text = payload["text"].strip()
            if text:
                transcripts.append(text)
        cursor = start + max(consumed, 1)

    return transcripts[-1] if transcripts else ""


class SherpaOnnxAsr:
    """Small adapter that can be replaced without changing the ROS node."""

    def __init__(
        self,
        executable,
        tokens,
        encoder,
        decoder,
        joiner,
        num_threads=2,
        timeout_seconds=90.0,
    ):
        self._executable = executable
        self._model_paths = (tokens, encoder, decoder, joiner)
        self._num_threads = int(num_threads)
        self._timeout_seconds = float(timeout_seconds)

    def transcribe(self, wav_path):
        missing = [path for path in self._model_paths if not Path(path).is_file()]
        if missing:
            raise FileNotFoundError("ASR model files missing: {}".format(missing))
        if not Path(wav_path).is_file():
            raise FileNotFoundError("recorded WAV not found: {}".format(wav_path))

        tokens, encoder, decoder, joiner = self._model_paths
        command = [
            self._executable,
            "--tokens={}".format(tokens),
            "--encoder={}".format(encoder),
            "--decoder={}".format(decoder),
            "--joiner={}".format(joiner),
            "--provider=cpu",
            "--num-threads={}".format(self._num_threads),
            "--decoding-method=greedy_search",
            str(wav_path),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("ASR inference timed out") from error

        output = "\n".join((completed.stdout or "", completed.stderr or ""))
        if completed.returncode != 0:
            detail = output.strip()[-500:]
            raise RuntimeError(
                "ASR exited with code {}: {}".format(completed.returncode, detail)
            )
        transcript = extract_transcript(output)
        if not transcript:
            raise RuntimeError("ASR returned no transcript; check speech level and silence")
        return transcript
