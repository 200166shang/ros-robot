"""原生语音传输的鉴权、握手与任务事件契约。"""

import asyncio
import json
import time

import pytest
from async_speech_fixture import acknowledge, event, speech_server

from robot_agent.voice._async_speech_task import (
    AsyncSpeechConnection,
    SpeechProtocolError,
    SpeechTransportError,
)


def test_native_handshake_binary_and_close(monkeypatch):
    """先握手再发送二进制，退出时真实本地socket关闭。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        received = []
        closed = asyncio.Event()

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            command = await acknowledge(socket)
            received.append(await socket.recv())
            await event(socket, command, "task-finished")
            await socket.wait_closed()
            closed.set()

        async with speech_server(monkeypatch, handler):
            connection = AsyncSpeechConnection({})
            task = await connection.open({"task": "asr"}, time.monotonic() + 1)
            await task.send_binary(b"pcm")
            assert (await task.receive())["header"]["event"] == "task-finished"
            await connection.aclose()
            await asyncio.wait_for(closed.wait(), 1)
            assert received == [b"pcm"]

    asyncio.run(scenario())


def test_handshake_wait_sends_no_audio_and_cancellation_closes(monkeypatch):
    """延迟回执期间只有run-task；取消必须关闭已经打开的socket。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        entered, closed = asyncio.Event(), asyncio.Event()
        messages = []

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            messages.append(await socket.recv())
            entered.set()
            async for message in socket:
                messages.append(message)
            closed.set()

        async with speech_server(monkeypatch, handler):
            connection = AsyncSpeechConnection({})
            opening = asyncio.create_task(
                connection.open({}, time.monotonic() + 1)
            )
            await entered.wait()
            assert len(messages) == 1
            opening.cancel()
            with pytest.raises(asyncio.CancelledError):
                await opening
            await asyncio.wait_for(closed.wait(), 1)
            await connection.aclose()
            assert len(messages) == 1

    asyncio.run(scenario())


def test_invalid_events_are_permanent_and_handshake_timeout_is_network(
    monkeypatch,
):
    """无效标识/JSON/事件/服务错误不伪装成可重连网络故障。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        for reply in [
            "broken-json",
            "wrong-id",
            "task-failed",
            "task-finished",
            "bad-kind",
        ]:

            async def handler(socket):
                """本机语音服务器提供可控事件并等待连接释放。"""
                command = json.loads(await socket.recv())
                if reply == "broken-json":
                    await socket.send("{")
                elif reply == "wrong-id":
                    command["header"]["task_id"] = "other"
                    await event(socket, command, "task-started")
                else:
                    await event(
                        socket, command, 42 if reply == "bad-kind" else reply
                    )
                await socket.wait_closed()

            async with speech_server(monkeypatch, handler):
                connection = AsyncSpeechConnection({})
                with pytest.raises(SpeechProtocolError):
                    await connection.open({}, time.monotonic() + 1)
                await connection.aclose()

        async def silent(socket):
            """保持握手无回执，观察超时与连接回收。"""
            await socket.recv()
            await socket.wait_closed()

        async with speech_server(monkeypatch, silent):
            connection = AsyncSpeechConnection({})
            with pytest.raises(SpeechTransportError, match="超时"):
                await connection.open({}, time.monotonic() + 0.04)
            await connection.aclose()

    asyncio.run(scenario())
