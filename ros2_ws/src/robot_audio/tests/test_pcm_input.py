"""通过外部PCM子进程验证持续采集与有界资源回收。"""

import os
import time

import pytest

from robot_audio.pcm_input import PcmMicrophone


def test_partial_pcm_frames_and_idle_close_reap_process(tmp_path):
    """部分帧正确拼接，设备空闲时关闭也回收实际录音子进程。"""
    pid_file = tmp_path / "pid"
    recorder = tmp_path / "recorder"
    recorder.write_text(
        "#!/usr/bin/python3\nimport os,sys,time\n"
        f"open({str(pid_file)!r},'w').write(str(os.getpid()))\n"
        "sys.stdout.buffer.write(b'\\x01\\x00' * 800)\n"
        "sys.stdout.buffer.flush()\ntime.sleep(.03)\n"
        "sys.stdout.buffer.write(b'\\x02\\x00' * 800)\n"
        "sys.stdout.buffer.flush()\ntime.sleep(60)\n"
    )
    recorder.chmod(0o755)
    source = PcmMicrophone(str(recorder), "fixture")
    source.start()
    try:
        frame = None
        deadline = time.monotonic() + 2
        while frame is None:
            assert time.monotonic() < deadline
            frame = source.read(3200)
        assert frame == b"\x01\x00" * 800 + b"\x02\x00" * 800
        assert source.read(3200, 0.01) is None
        source.discard()
    finally:
        source.close()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_pcm_eof_is_failure_not_silence(tmp_path):
    """设备退出不能冒充静音保活，部分帧也不能交付成功。"""
    recorder = tmp_path / "short-recorder"
    recorder.write_text(
        "#!/usr/bin/python3\nimport sys\nsys.stdout.write('bad')\n"
    )
    recorder.chmod(0o755)
    source = PcmMicrophone(str(recorder), "fixture")
    source.start()
    try:
        with pytest.raises(OSError, match="输入已结束"):
            while True:
                assert source.read(3200) is None
    finally:
        source.close()
