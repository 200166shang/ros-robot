"""本机异步语音协议验收：WAV输入、完整合成和取消。"""

import asyncio
import json
import wave

import pytest
from async_speech_fixture import acknowledge, event, final, speech_server

from robot_agent.voice.speech import DashScopeASR, DashScopeTTS


def fixture_wav(tmp_path):
    """构造非静音PCM16录音。"""
    path = tmp_path / "input.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 1600)
    return path


def test_native_wav_and_complete_tts(tmp_path, monkeypatch):
    """WAV只返回最终句，合成完整确认后才出现可播放音频。"""

    async def scenario():
        """真实本机socket保持事件循环活跃。"""
        frames = []

        async def handler(socket):
            """分别回应真实识别和合成控制协议。"""
            command = await acknowledge(socket)
            if command["payload"]["task"] == "asr":
                async for message in socket:
                    if isinstance(message, bytes):
                        frames.append(message)
                    else:
                        assert (
                            json.loads(message)["header"]["action"]
                            == "finish-task"
                        )
                        await final(socket, command, "真实句子")
                        await event(socket, command, "task-finished")
                        break
            else:
                assert (
                    json.loads(await socket.recv())["payload"]["input"]["text"]
                    == "回复"
                )
                assert (
                    json.loads(await socket.recv())["header"]["action"]
                    == "finish-task"
                )
                await socket.send(b"\x02\x00" * 1600)
                await asyncio.sleep(0.02)
                assert not (tmp_path / "reply.wav").exists()
                await event(socket, command, "task-finished")
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler):
            asr, tts = DashScopeASR({}), DashScopeTTS({})
            assert await asr.recognize(fixture_wav(tmp_path), 1) == "真实句子"
            destination = tmp_path / "reply.wav"
            await tts.synthesize("回复", destination, 1)
            with wave.open(str(destination)) as audio:
                assert audio.getnframes() == 1600
            assert frames == [b"\x01\x00" * 1600]
            assert list(tmp_path.glob("*.tmp")) == []
            await asr.aclose()
            await tts.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "failure",
    [
        "disconnect",
        "task-failed",
        "wrong-task",
        "empty",
        "odd-pcm",
        "timeout",
        "cancel",
    ],
)
def test_incomplete_tts_never_publishes_audio(tmp_path, monkeypatch, failure):
    """中断、错误、取消和无完整PCM均清除临时产物并关闭socket。"""

    async def scenario():
        """服务端控制完成条件，取消路径也必须等待连接释放。"""
        received, closed = asyncio.Event(), asyncio.Event()

        async def handler(socket):
            """先发部分音频，再模拟指定协议或网络结果。"""
            command = await acknowledge(socket)
            await socket.recv()
            await socket.recv()
            if failure != "empty":
                await socket.send(
                    b"x" if failure == "odd-pcm" else bytes(3200)
                )
            received.set()
            if failure == "disconnect":
                await socket.close()
            elif failure == "task-failed":
                await event(socket, command, "task-failed")
            elif failure in ("wrong-task", "empty", "odd-pcm"):
                if failure == "wrong-task":
                    command["header"]["task_id"] = "different-task"
                await event(socket, command, "task-finished")
            await socket.wait_closed()
            closed.set()

        async with speech_server(monkeypatch, handler):
            tts = DashScopeTTS({})
            destination = tmp_path / "reply.wav"
            synthesizing = asyncio.create_task(
                tts.synthesize("回复", destination, 0.08)
            )
            await received.wait()
            if failure == "cancel":
                synthesizing.cancel()
            with pytest.raises(
                asyncio.CancelledError if failure == "cancel" else OSError
            ):
                await synthesizing
            await asyncio.wait_for(closed.wait(), 1)
            assert not destination.exists()
            assert list(tmp_path.glob("*.tmp")) == []
            await tts.aclose()

    asyncio.run(scenario())


def test_wav_retry_replays_entire_file_with_fresh_sentences(
    tmp_path, monkeypatch
):
    """仅临时断线重试整文件，每次任务标识和句子集合独立。"""

    async def scenario():
        """第一个任务已返回最终句后断线，成功轮不能包含旧句。"""
        tasks, frames = [], []

        async def handler(socket):
            """记录每一轮完整音频，并只完成第二轮。"""
            command = await acknowledge(socket)
            tasks.append(command["header"]["task_id"])
            captured = []
            frames.append(captured)
            async for message in socket:
                if isinstance(message, bytes):
                    captured.append(message)
                else:
                    if len(tasks) == 1:
                        await final(socket, command, "失败轮句子")
                        await socket.close()
                    else:
                        await final(socket, command, "完整新句")
                        await event(socket, command, "task-finished")
                    break
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler):
            asr = DashScopeASR({})
            assert await asr.recognize(fixture_wav(tmp_path), 1) == "完整新句"
            assert len(set(tasks)) == 2
            assert frames == [[b"\x01\x00" * 1600]] * 2
            await asr.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("permanent", [False, True])
def test_wav_retry_budget_and_permanent_failure(
    tmp_path, monkeypatch, permanent
):
    """网络失败次数有限；协议错误只尝试一次而不自动重试。"""

    async def scenario():
        """持续断线不能借握手成功恢复尝试预算。"""
        tasks = []

        async def handler(socket):
            """握手后模拟永久任务失败或临时断线。"""
            command = await acknowledge(socket)
            tasks.append(command)
            if permanent:
                await event(socket, command, "task-failed")
                await socket.wait_closed()
            else:
                await socket.close()

        async with speech_server(monkeypatch, handler):
            asr = DashScopeASR({"asr_attempts": 2})
            with pytest.raises(OSError):
                await asr.recognize(fixture_wav(tmp_path), 1)
            assert len(tasks) == (1 if permanent else 2)
            await asr.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "format", [(2, 2, 16000), (1, 1, 16000), (1, 2, 8000), (1, 2, 16000)]
)
def test_invalid_wav_rejected_before_network(tmp_path, monkeypatch, format):
    """错误格式或空录音在连接前拒绝，不触发线上请求。"""

    async def scenario():
        """本地服务器若被访问即表明验证过晚。"""
        requests = []

        async def handler(socket):
            """记录禁止发生的外部调用。"""
            requests.append(await socket.recv())

        path = tmp_path / "invalid.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setparams((*format, 0, "NONE", "not compressed"))
            if format != (1, 2, 16000):
                wav.writeframes(bytes(3200))
        async with speech_server(monkeypatch, handler):
            asr = DashScopeASR({})
            with pytest.raises(ValueError):
                await asr.recognize(path, 1)
            assert requests == []
            await asr.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["asr", "tts"])
def test_close_during_handshake_releases_owned_operation(
    tmp_path, monkeypatch, operation
):
    """显式关闭取消握手中的业务任务并回收socket，不再重连。"""

    async def scenario():
        """服务器不回应握手，关闭必须自己结束等待。"""
        entered, closed = asyncio.Event(), asyncio.Event()
        requests = []

        async def handler(socket):
            """只接纳初始请求并观察连接关闭。"""
            requests.append(await socket.recv())
            entered.set()
            await socket.wait_closed()
            closed.set()

        async with speech_server(monkeypatch, handler):
            adapter = (
                DashScopeASR({}) if operation == "asr" else DashScopeTTS({})
            )
            pending = asyncio.create_task(
                adapter.recognize(fixture_wav(tmp_path), 10)
                if operation == "asr"
                else adapter.synthesize("回复", tmp_path / "reply.wav", 10)
            )
            await entered.wait()
            await adapter.aclose()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await asyncio.wait_for(closed.wait(), 1)
            assert len(requests) == 1
            assert list(tmp_path.glob("*.tmp")) == []

    asyncio.run(scenario())
