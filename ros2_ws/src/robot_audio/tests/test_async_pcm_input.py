"""用受控子进程验证原生异步PCM读取、切换和回收。"""

import asyncio
import os
from pathlib import Path

import pytest

from robot_audio.async_pcm_input import AsyncPcmMicrophone


def test_pcm_lazy_fragmented_read_discard_and_reap(tmp_path):
    """恢复切换清理部分帧与管道积压，退出回收真实子进程。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        command = tmp_path / "recorder"
        pid_file = tmp_path / "pid"
        queued = tmp_path / "queued"
        queue_gate = tmp_path / "queue-gate"
        new_gate = tmp_path / "new-gate"
        command.write_text(
            "#!/usr/bin/python3\nimport os,time\nfrom pathlib import Path\n"
            f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
            "os.write(1,b'old')\n"
            f"while not Path({str(queue_gate)!r}).exists(): time.sleep(.001)\n"
            "os.write(1,b'OLD!'*200)\n"
            f"Path({str(queued)!r}).touch()\n"
            f"while not Path({str(new_gate)!r}).exists(): time.sleep(.001)\n"
            "os.write(1,b'NEW!')\ntime.sleep(30)\n"
        )
        command.chmod(0o755)
        source = AsyncPcmMicrophone(str(command), "fixture")
        assert not pid_file.exists()
        await source.start()
        assert await source.read(4, 0.5) is None
        queue_gate.touch()

        async def wait_queued():
            """等待设备确认旧音频已进入内核管道。"""
            while not queued.exists():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait_queued(), 1)
        source.discard()
        reading = asyncio.create_task(source.read(4, 0.5))
        new_gate.touch()
        assert await reading == b"NEW!"
        await source.aclose()
        pid = int(Path(pid_file).read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("录音子进程未回收")

    asyncio.run(scenario())


def test_pcm_eof_reports_failure_and_close_reaps_child(tmp_path):
    """录音进程中途结束是输入故障，部分PCM不能冒充完整帧。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        command = tmp_path / "short-recorder"
        command.write_text(
            "#!/usr/bin/python3\nimport os\nos.write(1,b'xy')\n"
        )
        command.chmod(0o755)
        source = AsyncPcmMicrophone(str(command), "fixture")
        await source.start()
        try:
            assert await source.read(4, 0.5) is None
            with pytest.raises(OSError, match="PCM输入已结束"):
                await source.read(4, 0.5)
        finally:
            await source.aclose()

    asyncio.run(scenario())


def test_cancel_start_still_reaps_late_created_recorder(tmp_path, monkeypatch):
    """启动调用被取消时，迟到的真实录音进程仍归关闭操作持有。"""

    async def scenario():
        """在外部进程创建返回处控制竞争，不替换PCM实现。"""
        command = tmp_path / "recorder"
        pid_file = tmp_path / "pid"
        command.write_text(
            "#!/usr/bin/python3\nimport os,time\n"
            f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        command.chmod(0o755)
        created, release = asyncio.Event(), asyncio.Event()
        spawn = asyncio.create_subprocess_exec

        async def delayed_spawn(*args, **kwargs):
            """实际创建子进程，再延迟向Adapter交接资源。"""
            process = await spawn(*args, **kwargs)
            created.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_spawn)
        source = AsyncPcmMicrophone(str(command), "fixture")
        starting = asyncio.create_task(source.start())
        await asyncio.wait_for(created.wait(), 1)

        async def wait_pid():
            """等待外部子进程写入身份后再触发取消。"""
            while not pid_file.exists():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait_pid(), 1)
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        closing = asyncio.create_task(source.aclose())
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, 1)
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)

    asyncio.run(scenario())
