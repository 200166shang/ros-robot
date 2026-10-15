"""通过应用入口验证退出预算、事实保留及资源归属。"""

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from async_speech_fixture import acknowledge, event, speech_server
from native_protocol_fixture import native_response
from test_online_live_input import PcmFixture
from test_online_speech import fixture_wav
from test_online_voice import FixedModel, FixedSpeech, FixedTTS, make_voice
from websockets.asyncio import client
from websockets.asyncio.client import ClientConnection

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.application import AgentApplication
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.memory import ConversationMemory
from robot_agent.conversation.provider import DashScopeProvider
from robot_agent.results import ModelReply
from robot_agent.shutdown import ShutdownError
from robot_agent.voice.live_input import LiveSpeechInput
from robot_agent.voice.speech import DashScopeASR, DashScopeTTS
from robot_audio.async_pcm_input import AsyncPcmMicrophone
from robot_audio.async_playback import AsyncWavPlayer


@pytest.mark.parametrize("prior_output", [False, True])
@pytest.mark.parametrize("record_failure", [False, True])
def test_shutdown_saves_confirmed_turn_after_summary_programming_error(
    tmp_path, monkeypatch, prior_output, record_failure
):
    """摘要错误保持原样传播；退出必须保存尚未进入语音输出的动作事实。"""

    async def scenario():
        """先通过真实 Agent 确认动作，再检查公开关闭入口的产物。"""

        class Model(FixedModel):
            """仅摘要阶段抛出编程错误，动作请求仍使用固定模型 Seam。"""

            async def complete(self, text, deadline, *, tools=None):
                """动作后发生的摘要故障不能被误判为外部临时故障。"""
                if tools is None:
                    raise RuntimeError("summary implementation failure")
                return await super().complete(text, deadline, tools=tools)

        capabilities = create_default_actions()
        agent = Agent(
            Model(),
            capabilities.registry,
            memory=ConversationMemory(tmp_path / "memory", 1, 1),
        )
        tts = FixedTTS()
        app = AgentApplication(
            agent, None, tts, tmp_path, capabilities.music_playing
        )
        local = (
            await app.submit_transcript("小莫小莫") if prior_output else None
        )
        with pytest.raises(
            RuntimeError, match="summary implementation failure"
        ):
            await app.submit_transcript("点头", direct=True)
        original = agent.last_result
        assert original.actions[0].status == "simulated_success"
        assert len(tts.replies) == int(prior_output)
        destination = tmp_path / (original.turn_id + ".json")
        assert not destination.exists()
        if record_failure:

            def fail_replace(path, destination):
                """仅在公开关闭阶段让原子保存失败。"""
                raise OSError("record disk failed")

            monkeypatch.setattr(Path, "replace", fail_replace)
            with pytest.raises(OSError, match="退出回合记录保存失败"):
                await app.aclose()
            assert not destination.exists()
        else:
            await app.aclose()
            saved = json.loads(destination.read_text())
            assert saved["actions"][0]["status"] == "simulated_success"
            assert saved["transcript"] == "点头"
            assert "audio_path" not in saved
            if local is not None:
                prior = json.loads(
                    (tmp_path / (local.turn_id + ".json")).read_text()
                )
                assert prior["audio_path"] == local.audio_path
                assert prior["status"] == "woken"
        assert original.actions[0].status == "simulated_success"

    asyncio.run(scenario())


def test_shutdown_uses_one_budget_and_attempts_every_closer(tmp_path):
    """多个慢外部关闭共享期限，故障不能跳过其他资源。"""

    async def scenario():
        """通过已批准的应用Seam观察关闭时长与资源回收。"""
        application, speech, model, tts = make_voice(tmp_path)
        closed = []

        async def slow_input(deadline=None):
            """外部输入关闭消耗剩余预算。"""
            try:
                await asyncio.sleep(1)
            finally:
                closed.append("input")

        async def slow_output(deadline=None):
            """合成连接关闭与输入并行消耗同一预算。"""
            try:
                await asyncio.sleep(1)
            finally:
                closed.append("tts")

        async def broken_model(deadline=None):
            """关闭失败必须继续显露。"""
            closed.append("model")
            raise RuntimeError("broken model closer")

        speech.aclose = slow_input
        tts.aclose = slow_output
        model.aclose = broken_model
        started = time.monotonic()
        with pytest.raises(Exception):
            await application.aclose(started + 0.06)
        assert time.monotonic() - started < 0.3
        assert set(closed) == {"input", "tts", "model"}
        assert (
            await application.submit_transcript("点头")
        ).status == "rejected"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "phase",
    [
        "start",
        "connect",
        "handshake",
        "first_frame",
        "send",
        "receive",
        "reconnect",
    ],
)
def test_application_close_during_native_input_acquisition(
    tmp_path, monkeypatch, phase
):
    """直接关闭每个资源获取阶段，零重连、无迟到音频且清理调用可并发。"""

    async def scenario():
        """门控真实loopback连接及PCM外部Seam，不读取模块内部状态。"""
        ready, gate = asyncio.Event(), asyncio.Event()
        sockets, frames, connections = [], [], []
        original_send, original_recv = (
            ClientConnection.send,
            ClientConnection.recv,
        )
        handshakes = 0

        class Source(PcmFixture):
            """在设备获取或首帧读取前提供确定性门控。"""

            async def start(self):
                """关闭可以发生在录音设备启动尚未返回时。"""
                if phase == "start":
                    ready.set()
                    await gate.wait()
                await super().start()

            async def read(self, size, timeout=0.2):
                """首帧阻塞不能阻止退出。"""
                if phase == "first_frame":
                    ready.set()
                    await gate.wait()
                return await super().read(size, timeout)

        async def send(socket, message, *args, **kwargs):
            """真实WebSocket发送在背压处可被退出解除。"""
            if phase == "send" and isinstance(message, bytes):
                ready.set()
                await gate.wait()
            return await original_send(socket, message, *args, **kwargs)

        async def recv(socket, *args, **kwargs):
            """握手后的接收在无下一帧时保持阻塞。"""
            if phase == "receive" and handshakes:
                ready.set()
                await gate.wait()
            return await original_recv(socket, *args, **kwargs)

        async def handler(socket):
            """只有真实握手进入后，才允许测试触发相应阶段关闭。"""
            nonlocal handshakes
            sockets.append(socket)
            if phase == "handshake":
                json.loads(await socket.recv())
                ready.set()
                await socket.wait_closed()
                return
            await acknowledge(socket)
            handshakes += 1
            if phase == "reconnect":
                await socket.close()
                return
            async for frame in socket:
                frames.append(frame)

        monkeypatch.setattr(ClientConnection, "send", send)
        monkeypatch.setattr(ClientConnection, "recv", recv)
        async with speech_server(monkeypatch, handler) as scoped:
            connect = client.connect

            async def connecting(*args, **kwargs):
                """连接前或重连前停止，不建立关闭后的新连接。"""
                connections.append(1)
                if phase == "connect" or (
                    phase == "reconnect" and len(connections) == 2
                ):
                    ready.set()
                    await gate.wait()
                return await connect(*args, **kwargs)

            scoped.setattr(client, "connect", connecting)
            source = Source()
            live = LiveSpeechInput({"asr_attempts": 4}, source)
            capabilities = create_default_actions()
            app = AgentApplication(
                Agent(FixedModel(), capabilities.registry),
                live,
                FixedTTS(),
                tmp_path,
                music_playing=capabilities.music_playing,
                shutdown_timeout=0.15,
            )
            running = asyncio.create_task(app.run(lambda record: None))
            await asyncio.wait_for(ready.wait(), 2)
            started = time.monotonic()
            await asyncio.gather(app.aclose(), app.aclose())
            assert time.monotonic() - started < 0.4
            await asyncio.wait_for(running, 0.3)
            assert source.closed
            assert all(socket.state.name == "CLOSED" for socket in sockets)
            assert not frames
            assert len(connections) <= (2 if phase == "reconnect" else 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("late", [False, True])
def test_shutdown_persists_original_action_facts_without_remainder(
    tmp_path, late
):
    """退出接收期限内的原回执；到期只保存未知，不重发或补执行。"""

    async def scenario():
        """真实执行Interface等待受控设备回执，检查既有JSON事实。"""
        entered, receipt = asyncio.Event(), asyncio.Event()
        calls = []
        capabilities = create_default_actions()

        async def nod():
            """只提交一次设备调用。"""
            calls.append("nod")
            entered.set()
            await receipt.wait()
            return {
                "status": "real_success",
                "detail": "original confirmation",
            }

        def shake():
            """关闭后剩余动作必须保持未执行。"""
            calls.append("shake")
            return {"status": "real_success"}

        capabilities.registry.register("head_nod", nod)
        capabilities.registry.register("head_shake", shake)
        model, speech = FixedModel(), FixedSpeech()
        model.actions = [
            {"name": "head_nod", "arguments": {}},
            {"name": "head_shake", "arguments": {}},
        ]
        agent = Agent(model, capabilities.registry, action_timeout=1)
        app = AgentApplication(
            agent,
            speech,
            FixedTTS(),
            tmp_path,
            music_playing=capabilities.music_playing,
            shutdown_timeout=0.06,
        )
        turn = asyncio.create_task(
            app.submit_transcript("点头并摇头", direct=True)
        )
        await entered.wait()
        closing = asyncio.create_task(app.aclose())
        await asyncio.sleep(0)
        if not late:
            receipt.set()
        await closing
        await asyncio.gather(turn, return_exceptions=True)
        result = agent.last_result
        assert result is not None
        original = result
        data = json.loads((tmp_path / (result.turn_id + ".json")).read_text())
        assert [item["status"] for item in data["actions"]] == [
            "unknown" if late else "real_success",
            "not_executed",
        ]
        assert calls == ["nod"]
        assert "resume" not in speech.events
        receipt.set()
        await asyncio.sleep(0)
        assert original.actions[0].status == (
            "unknown" if late else "real_success"
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("summary", [False, True])
def test_closing_model_completion_cannot_submit_actions_or_apply_summary(
    tmp_path, summary
):
    """取消竞争中迟到的模型回复不能启动动作或回写旧摘要。"""

    async def scenario():
        """外部模型故意让一次回复完成赢过取消，验证停止状态契约。"""
        entered = asyncio.Event()
        completed_after_stop = []
        capabilities = create_default_actions()
        calls = []

        def nod():
            """退出后不能发出的新动作。"""
            calls.append("nod")
            return {"status": "real_success"}

        capabilities.registry.register("head_nod", nod)

        class Model(FixedModel):
            """可控模型在取消竞争中仍返回完整回复。"""

            async def complete(self, text, deadline, *, tools=None):
                """普通请求或摘要等待到关闭触发取消。"""
                if summary and tools is not None:
                    return ModelReply("已确认聊天")
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    await asyncio.sleep(0.02)
                    completed_after_stop.append(True)
                    return (
                        ModelReply("退出后的旧摘要")
                        if summary
                        else await super().complete(
                            text, deadline, tools=tools
                        )
                    )

        memory_file = tmp_path / "summary.json"
        agent = Agent(
            Model(),
            capabilities.registry,
            memory=ConversationMemory(
                memory_file, recent_turns=1, summary_trigger=1
            ),
        )
        app = AgentApplication(
            agent,
            FixedSpeech(),
            FixedTTS(),
            tmp_path / "output",
            music_playing=capabilities.music_playing,
            shutdown_timeout=0.15,
        )
        turn = asyncio.create_task(app.submit_transcript("请求", direct=True))
        await entered.wait()
        await app.aclose()
        await asyncio.gather(turn, return_exceptions=True)
        assert calls == []
        assert completed_after_stop == [True]
        assert not memory_file.exists()
        assert (
            await app.submit_transcript("重试", direct=True)
        ).status == "rejected"

    asyncio.run(scenario())


def test_cancelled_shutdown_waiter_does_not_abandon_cleanup(tmp_path):
    """取消第一个关闭等待者后，第二个调用继续等待唯一清理操作。"""

    async def scenario():
        """原关闭任务持有慢输入，不由调用者取消夺走资源归属。"""
        app, speech, model, tts = make_voice(tmp_path, shutdown_timeout=0.2)
        entered, release = asyncio.Event(), asyncio.Event()
        closed = []

        async def close(deadline=None):
            """外部输入延迟关闭，记录唯一关闭次数。"""
            entered.set()
            await release.wait()
            closed.append(True)

        speech.aclose = close
        first = asyncio.create_task(app.aclose())
        await entered.wait()
        established = app.shutdown_deadline
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(app.aclose(time.monotonic() + 10))
        await asyncio.sleep(0)
        assert not second.done()
        assert app.shutdown_deadline == established
        release.set()
        await second
        assert closed == [True]

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["tts", "player", "pcm"])
def test_native_audio_shutdown_reaps_children_and_preserves_complete_audio(
    tmp_path, monkeypatch, phase
):
    """流式合成、播放器和不完整PCM持有资源都在应用退出时回收。"""

    async def scenario():
        """真实本机socket和受控子进程，不访问麦克风或声音设备。"""
        ready = asyncio.Event()
        sockets = []
        pid_file = tmp_path / "pid"
        executable = tmp_path / "audio-child"
        executable.write_text(
            "#!/usr/bin/python3\nimport os,time,signal\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
            + ("os.write(1,b'x')\n" if phase == "pcm" else "")
            + "time.sleep(30)\n"
        )
        executable.chmod(0o755)

        async def handler(socket):
            """TTS送出部分PCM后阻塞，播放器场景则提供完整输出。"""
            command = await acknowledge(socket)
            sockets.append(socket)
            if phase != "pcm":
                await socket.recv()
                await socket.recv()
                await socket.send(bytes(3200))
                if phase == "player":
                    await event(socket, command, "task-finished")
                else:
                    ready.set()
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler):
            capabilities = create_default_actions()
            agent = Agent(FixedModel(), capabilities.registry)
            source = (
                AsyncPcmMicrophone(str(executable), "fixture")
                if phase == "pcm"
                else None
            )
            speech = (
                LiveSpeechInput({}, source)
                if source is not None
                else FixedSpeech()
            )
            app = AgentApplication(
                agent,
                speech,
                DashScopeTTS({}),
                tmp_path / "output",
                music_playing=capabilities.music_playing,
                playback=AsyncWavPlayer(str(executable), "fixture")
                if phase == "player"
                else None,
                shutdown_timeout=0.1,
            )
            running = asyncio.create_task(
                app.run(lambda result: None)
                if phase == "pcm"
                else app.submit_transcript("点头", direct=True)
            )
            if phase == "tts":
                await asyncio.wait_for(ready.wait(), 2)
            else:

                async def child_started():
                    """只有实际子进程写入PID后才开始退出。"""
                    while not pid_file.exists():
                        await asyncio.sleep(0.001)

                await asyncio.wait_for(child_started(), 2)
            started = time.monotonic()
            await app.aclose()
            assert time.monotonic() - started < 0.35
            await asyncio.gather(running, return_exceptions=True)
            if phase != "tts":
                with pytest.raises(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), 0)
            assert all(socket.state.name == "CLOSED" for socket in sockets)
            assert list((tmp_path / "output").glob("*.tmp")) == []
            if phase != "pcm":
                saved = json.loads(
                    next((tmp_path / "output").glob("*.json")).read_text()
                )
                assert saved["actions"][0]["status"] == "simulated_success"
                if phase == "player":
                    assert saved["tts_status"] == "completed"
                    assert saved["audio_path"]
                    assert saved["playback_status"] != "completed"
                else:
                    assert list((tmp_path / "output").glob("*.wav")) == []

    asyncio.run(scenario())


@pytest.mark.parametrize("summary", [False, True])
def test_local_http_request_and_slow_response_cleanup_share_shutdown_budget(
    tmp_path, monkeypatch, summary
):
    """真实本机HTTP模型/摘要请求及慢响应收尾不重试、不阻塞循环。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")

    async def scenario():
        """外部HTTP端点留在loopback，生产Adapter仍拥有请求与流关闭。"""
        ready, closed = asyncio.Event(), asyncio.Event()
        requests, handlers, response_closes = [], [], []

        async def handler(reader, writer):
            """第一个聊天可完成，目标请求在响应正文中保持阻塞。"""
            handlers.append(asyncio.current_task())
            target = False
            try:
                while True:
                    try:
                        headers = await reader.readuntil(b"\r\n\r\n")
                    except asyncio.IncompleteReadError:
                        return
                    length = next(
                        int(line.split(b":", 1)[1])
                        for line in headers.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                    requests.append(
                        json.loads(await reader.readexactly(length))
                    )
                    if summary and len(requests) == 1:
                        body = native_response(
                            response="已确认聊天"
                        ).getvalue()
                        writer.write(
                            b"HTTP/1.1 200 OK\r\nContent-Length: "
                            + str(len(body)).encode()
                            + b"\r\n\r\n"
                            + body
                        )
                        await writer.drain()
                        continue
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: 10000\r\n\r\n"
                    )
                    await writer.drain()
                    target = True
                    ready.set()
                    assert await reader.read() == b""
                    return
            finally:
                writer.close()
                await writer.wait_closed()
                if target:
                    closed.set()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        async def route(request):
            """仅路由外部传输，不替换模型解析和请求任务。"""
            request.url = httpx.URL(f"http://127.0.0.1:{port}/model")

        class SlowResponse(httpx.AsyncByteStream):
            """实际HTTP响应在释放时消耗可观察的一部分剩余预算。"""

            def __init__(self, stream):
                """接管同一原始网络响应。"""
                self.stream = stream

            async def __aiter__(self):
                """原样读取真实网络字节。"""
                async for data in self.stream:
                    yield data

            async def aclose(self):
                """不遗漏原始socket关闭。"""
                try:
                    await asyncio.sleep(0.02)
                finally:
                    await self.stream.aclose()
                    response_closes.append(True)

        async def slow_response(response):
            """在真实网络响应Seam加入已规定的慢清理场景。"""
            response.stream = SlowResponse(response.stream)

        client = httpx.AsyncClient(
            trust_env=False,
            event_hooks={"request": [route], "response": [slow_response]},
        )
        capabilities = create_default_actions()
        agent = Agent(
            DashScopeProvider({}, client=client),
            capabilities.registry,
            memory=ConversationMemory(
                tmp_path / "summary.json", recent_turns=1, summary_trigger=1
            ),
        )
        app = AgentApplication(
            agent,
            FixedSpeech(),
            FixedTTS(),
            tmp_path / "output",
            music_playing=capabilities.music_playing,
            shutdown_timeout=0.15,
        )
        turn = asyncio.create_task(app.submit_transcript("聊天", direct=True))
        beats = []

        async def heartbeat():
            """请求与清理期间事件循环必须持续运行。"""
            for _ in range(10):
                beats.append(1)
                await asyncio.sleep(0.005)

        ticker = asyncio.create_task(heartbeat())
        try:
            await asyncio.wait_for(ready.wait(), 2)
            started = time.monotonic()
            await app.aclose()
            assert time.monotonic() - started < 0.35
            await asyncio.gather(turn, return_exceptions=True)
            await asyncio.wait_for(closed.wait(), 0.3)
            assert client.is_closed
            saved = json.loads(
                next((tmp_path / "output").glob("*.json")).read_text()
            )
            assert saved["reply"] == agent.last_result.reply
            assert response_closes
            assert len(requests) == (2 if summary else 1)
            assert not (tmp_path / "summary.json").exists()
            if summary:
                assert agent.last_result.reply == "已确认聊天"
                assert agent.last_result.status == "completed"
            await ticker
            assert len(beats) == 10
        finally:
            server.close()
            await server.wait_closed()
            await asyncio.gather(*handlers)

    asyncio.run(scenario())


def test_broken_closer_and_failed_exit_record_are_both_observable(
    tmp_path, monkeypatch
):
    """单个连接清理和记录均失败时仍关闭其他资源，保留两种失败事实。"""

    async def scenario():
        """先确认动作，再分别注入外部关闭及文件系统故障。"""
        app, speech, model, tts = make_voice(tmp_path)
        original = await app.submit_transcript("点头", direct=True)
        assert original.actions[0].status == "simulated_success"
        closed = []

        async def broken(deadline=None):
            """输入关闭失败不能跳过模型和TTS。"""
            closed.append("input")
            raise RuntimeError("broken input close")

        async def close_model(deadline=None):
            """模型连接回收可以被公开观察。"""
            closed.append("model")

        async def close_tts(deadline=None):
            """TTS连接回收可以被公开观察。"""
            closed.append("tts")

        def fail_replace(path, destination):
            """仅在退出阶段注入记录写入失败。"""
            raise OSError("record disk failed")

        speech.aclose, model.aclose, tts.aclose = (
            broken,
            close_model,
            close_tts,
        )
        monkeypatch.setattr(Path, "replace", fail_replace)
        with pytest.raises(ShutdownError) as caught:
            await app.aclose()
        assert set(closed) == {"input", "model", "tts"}
        assert any(
            isinstance(error, RuntimeError) for error in caught.value.errors
        )
        assert any(isinstance(error, OSError) for error in caught.value.errors)
        assert original.actions[0].status == "simulated_success"
        assert list(tmp_path.glob("*.tmp")) == []

    asyncio.run(scenario())


def test_recording_close_reclaims_native_file_recognition(
    tmp_path, monkeypatch
):
    """独立文件识别取消关闭原连接和收发任务，不提交模型或重连。"""

    async def scenario():
        """实际WAV与本机语音任务在识别尚未完成时开始应用关闭。"""
        ready = asyncio.Event()
        sockets = []

        async def handler(socket):
            """接收实际音频后阻塞最终句与完成事件。"""
            await acknowledge(socket)
            sockets.append(socket)
            assert isinstance(await socket.recv(), bytes)
            ready.set()
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler):
            model = FixedModel()
            capabilities = create_default_actions()
            app = AgentApplication(
                Agent(model, capabilities.registry),
                None,
                FixedTTS(),
                tmp_path / "output",
                music_playing=capabilities.music_playing,
                recording_input=DashScopeASR({}),
                shutdown_timeout=0.15,
            )
            turn = asyncio.create_task(
                app.submit_recording(fixture_wav(tmp_path))
            )
            await asyncio.wait_for(ready.wait(), 2)
            await asyncio.gather(app.aclose(), app.aclose())
            await asyncio.gather(turn, return_exceptions=True)
            assert not model.inputs
            assert len(sockets) == 1
            assert sockets[0].state.name == "CLOSED"
            assert (
                await app.submit_recording(tmp_path / "missing.wav")
            ).status == "rejected"

    asyncio.run(scenario())


@pytest.mark.parametrize("unresolved", [False, True])
def test_shutdown_keeps_original_audio_after_local_output(
    tmp_path, unresolved
):
    """等待动作期间本地唤醒另有输出，最终确认仍保留原动作产物及快照。"""

    async def scenario():
        """原未知回合的音频不得被较新的会话本地记录覆盖。"""
        receipt = asyncio.Event()
        capabilities = create_default_actions()

        async def nod():
            """设备只完成原始调用。"""
            if unresolved:
                await receipt.wait()
            return {"status": "real_success"}

        capabilities.registry.register("head_nod", nod)
        app = AgentApplication(
            Agent(FixedModel(), capabilities.registry, action_timeout=0.01),
            FixedSpeech(),
            FixedTTS(),
            tmp_path,
            music_playing=capabilities.music_playing,
            shutdown_timeout=0.2,
        )
        original = await app.submit_transcript("点头", direct=True)
        status = "unknown" if unresolved else "real_success"
        assert original.actions[0].status == status
        local = await app.submit_transcript("小莫小莫")
        assert local.status == "woken"
        closing = asyncio.create_task(app.aclose())
        await asyncio.sleep(0)
        receipt.set()
        await closing
        saved = json.loads(
            (tmp_path / (original.turn_id + ".json")).read_text()
        )
        assert saved["actions"][0]["status"] == "real_success"
        assert saved["transcript"] == "点头"
        assert saved["audio_path"] == original.audio_path
        assert saved["tts_status"] == "completed"
        assert original.actions[0].status == status
        local_path = tmp_path / (local.turn_id + ".json")
        assert json.loads(local_path.read_text())["status"] == "woken"

    asyncio.run(scenario())
