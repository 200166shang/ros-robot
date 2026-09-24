"""Sherpa-ONNX CLI adapter for the local Chinese Piper VITS voice."""

import subprocess
import wave
from pathlib import Path


class SherpaOnnxTts:
    """Generate a WAV without coupling model inference to ROS or ALSA."""

    def __init__(
        self,
        executable,
        model,
        lexicon,
        tokens,
        rule_fsts,
        num_threads=2,
        timeout_seconds=90.0,
    ):
        self._executable = executable
        self._model_paths = (model, lexicon, tokens)
        self._rule_fsts = rule_fsts
        self._num_threads = int(num_threads)
        self._timeout_seconds = float(timeout_seconds)

    def synthesize(self, text, output_path):
        text = text.strip()
        if not text:
            raise ValueError("cannot synthesize an empty response")
        missing = [path for path in self._model_paths if not Path(path).is_file()]
        if missing:
            raise FileNotFoundError("TTS model files missing: {}".format(missing))

        model, lexicon, tokens = self._model_paths
        command = [
            self._executable,
            "--num-threads={}".format(self._num_threads),
            "--vits-model={}".format(model),
            "--vits-lexicon={}".format(lexicon),
            "--vits-tokens={}".format(tokens),
            "--tts-rule-fsts={}".format(self._rule_fsts),
            "--output-filename={}".format(output_path),
            text,
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
            raise RuntimeError("TTS synthesis timed out") from error

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-500:]
            raise RuntimeError(
                "TTS exited with code {}: {}".format(completed.returncode, detail)
            )

        output_path = Path(output_path)
        if not output_path.is_file() or output_path.stat().st_size <= 44:
            raise RuntimeError("TTS did not produce a non-empty WAV file")
        try:
            with wave.open(str(output_path), "rb") as audio:
                if audio.getnframes() <= 0:
                    raise RuntimeError("TTS produced a WAV with no audio frames")
        except (OSError, wave.Error) as error:
            raise RuntimeError("TTS output is not a valid WAV file") from error
        return output_path
