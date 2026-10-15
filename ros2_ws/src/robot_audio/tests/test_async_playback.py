"""原生异步播放器的非阻塞等待与子进程回收。"""

import asyncio
import os
import time
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
        deadline = time.monotonic() + 2
        while not pid_file.exists():
            assert time.monotonic() < deadline
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


@pytest.mark.parametrize("mode", ["nonzero", "timeout"])
def test_player_failure_and_timeout_reap_child(tmp_path, mode):
    """非零退出和超时均报告I/O错误，完整WAV保留且进程已回收。"""
    executable = tmp_path / "player"
    pid_file = tmp_path / "pid"
    executable.write_text(
        "#!/usr/bin/python3\nimport os, sys, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        + ("sys.exit(7)\n" if mode == "nonzero" else "time.sleep(60)\n")
    )
    executable.chmod(0o755)
    path = tmp_path / "reply.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(3200))

    async def scenario():
        """使用很短期限而不访问真实播放设备。"""
        player = AsyncWavPlayer(
            str(executable),
            "fixture",
            timeout_margin=1 if mode == "nonzero" else 0.4,
        )
        with pytest.raises(
            OSError, match="退出码7" if mode == "nonzero" else "超时"
        ):
            await player(path)
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
        assert path.exists()

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_count", [1, 2])
def test_cancel_during_spawn_retains_late_child_ownership(
    tmp_path, monkeypatch, cancel_count
):
    """取消子进程建立等待后，迟到返回的播放器仍被终止回收。"""
    path = tmp_path / "reply.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(3200))

    async def scenario():
        """只在操作系统进程建立Seam延迟，不替换播放器。"""
        spawn = asyncio.create_subprocess_exec
        entered, release = asyncio.Event(), asyncio.Event()
        children = []

        async def delayed_spawn(*args, **kwargs):
            """保持真实进程建立，延迟将资源交给拥有者。"""
            process = await spawn(
                "/usr/bin/python3",
                "-c",
                "import time; time.sleep(60)",
                **kwargs,
            )
            children.append(process)
            entered.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
        pending = asyncio.create_task(
            AsyncWavPlayer("fixture", "fixture")(path)
        )
        await entered.wait()
        for _ in range(cancel_count):
            pending.cancel()
            await asyncio.sleep(0)
        release.set()
        try:
            with pytest.raises(asyncio.CancelledError):
                await pending
            with pytest.raises(ProcessLookupError):
                os.kill(children[0].pid, 0)
        finally:
            if children[0].returncode is None:
                children[0].kill()
                await children[0].wait()

    asyncio.run(scenario())
