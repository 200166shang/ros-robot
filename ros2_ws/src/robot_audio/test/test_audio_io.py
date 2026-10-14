"""通过公开录音/播放 Interface 验证退出确实终止音频子进程。"""

import os
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest

from robot_audio.audio_io import play_wav, record_wav


@pytest.mark.parametrize("operation", ["record", "play"])
def test_cancelled_audio_process_is_reaped(tmp_path, operation):
    """退出信号终止在途音频进程，返回前回收子进程。"""
    executable = tmp_path / "audio-device"
    executable.write_text(
        "#!/usr/bin/python3\n"
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[2]).write_text(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    executable.chmod(0o755)
    marker = tmp_path / "pid"
    wav = tmp_path / "audio.wav"
    with wave.open(str(wav), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(16000 * 2))
    stopped = threading.Event()
    with ThreadPoolExecutor() as executor:
        if operation == "record":
            future = executor.submit(
                record_wav,
                str(executable),
                str(marker),
                60,
                wav,
                cancelled=stopped.is_set,
            )
        else:
            future = executor.submit(
                play_wav,
                str(executable),
                str(marker),
                wav,
                cancelled=stopped.is_set,
            )
        deadline = time.monotonic() + 2
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        pid = int(marker.read_text())
        stopped.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            future.result(timeout=2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
