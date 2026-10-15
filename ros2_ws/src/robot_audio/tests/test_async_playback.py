"""原生异步播放器的非阻塞等待与子进程回收。"""

import asyncio
import os
import wave

import pytest

from robot_audio.async_playback import AsyncWavPlayer


def test_cancel_player_reaps_child_without_blocking_loop(tmp_path):
    """受控播放器仍在运行时取消，事件循环活跃且PID被回收。"""
    executable = tmp_path / "player"
    pid_file = tmp_path / "pid"
    executable.write_text(
        "#!/usr/bin/python3\nimport os, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "time.sleep(60)\n"
    )
    executable.chmod(0o755)
    audio = tmp_path / "reply.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(3200))

    async def scenario():
        """等待PID的循环同时验证心跳可推进。"""
        player = AsyncWavPlayer(str(executable), "fixture")
        playing = asyncio.create_task(player(audio))
        heartbeats = 0
        while not pid_file.exists():
            heartbeats += 1
            await asyncio.sleep(0.005)
        assert heartbeats > 0
        playing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await playing
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
        assert audio.exists()

    asyncio.run(scenario())
