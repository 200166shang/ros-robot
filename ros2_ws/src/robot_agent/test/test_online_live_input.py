"""通过原生WebSocket和PCM Seam验证持续输入与半双工交接。"""

import asyncio

import pytest
from async_speech_fixture import acknowledge, event, final, speech_server
from websockets.asyncio import client
from websockets.asyncio.client import ClientConnection

from robot_agent.voice.live_input import LiveSpeechInput


class PcmFixture:
    """以固定节奏交付可辨认PCM，记录实际设备生命周期。"""

    def __init__(self):
        """只保存测试设备状态，不启动读取。"""
        self.frames = 0
        self.started = False
        self.closed = False
        self.discards = 0

    async def start(self):
        """打开外部PCM源。"""
        self.started = True

    async def read(self, size, timeout=0.2):
        """每帧标记独立采集次序。"""
        await asyncio.sleep(0.01)
        self.frames += 1
        return self.frames.to_bytes(2, "little") * (size // 2)

    def discard(self):
        """回执恢复时丢弃源积压。"""
        self.discards += 1

    async def aclose(self):
        """关闭实际设备。"""
        self.closed = True


async def until(predicate):
    """等待外部可观察回执，超时明确失败。"""

    async def wait():
        """等待设备或网络的公开回执。"""
        while not predicate():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(wait(), 2)


def test_live_pause_drains_keeps_silence_and_delivers_one_final(monkeypatch):
    """一个持续任务跨回合，超时不取消任务，暂停丢弃且新回合可重复文本。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        frames, sockets = [], []
        command_ready = asyncio.Event()

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            command = await acknowledge(socket)
            sockets.append((socket, command))
            command_ready.set()
            async for frame in socket:
                frames.append(frame)

        async with speech_server(monkeypatch, handler):
            source = PcmFixture()
            live = LiveSpeechInput({}, source)
            assert not source.started
            try:
                assert await live.listen(0.02) is None
                await command_ready.wait()
                await until(lambda: len(frames) >= 2)
                socket, command = sockets[0]
                await event(
                    socket,
                    command,
                    "result-generated",
                    {"output": {"sentence": {"sentence_end": False}}},
                )
                await event(
                    socket,
                    command,
                    "result-generated",
                    {
                        "output": {
                            "sentence": {
                                "sentence_end": True,
                                "heartbeat": True,
                            }
                        }
                    },
                )
                assert await live.listen(0.02) is None
                await final(socket, command, "相同句", 0)
                assert await live.listen(1) == "相同句"
                baseline = len(frames)
                await until(lambda: len(frames) >= baseline + 3)
                assert frames[-2:] == [bytes(3200)] * 2
                before = source.frames
                await final(socket, command, "暂停旧句", 0)
                assert await live.listen(0.03) is None
                assert source.frames > before
                live.resume()
                await final(socket, command, "迟到旧句", 0)
                assert await live.listen(0.03) is None
                await final(socket, command, "相同句", len(frames) * 100)
                assert await live.listen(1) == "相同句"
                assert await live.listen(0.02) is None
                assert len(sockets) == 1
                assert source.discards >= 2
            finally:
                await live.aclose()
            assert source.closed

    asyncio.run(scenario())


def test_pcm_failure_wakes_idle_receiver_without_reconnect(monkeypatch):
    """设备失败不能等待服务端事件，也不能消耗网络重连后继续录音。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        sockets = []

        class BrokenPcm(PcmFixture):
            """第一帧之后报告具体设备错误。"""

            async def read(self, size, timeout=0.2):
                """只产生一帧，随后确定性失败。"""
                if self.frames:
                    raise OSError("PCM device failed")
                return await super().read(size, timeout)

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            await acknowledge(socket)
            sockets.append(socket)
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler):
            source = BrokenPcm()
            live = LiveSpeechInput({}, source)
            try:
                with pytest.raises(OSError, match="PCM device failed"):
                    await live.listen(1)
            finally:
                await live.aclose()
            assert source.closed
            assert len(sockets) <= 1

    asyncio.run(scenario())


def test_reconnect_success_does_not_reset_failure_budget(monkeypatch):
    """两次已握手断线耗尽预算，连接成功本身不是识别成功。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        connections = []

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            await acknowledge(socket)
            connections.append(socket)
            await socket.close()

        async with speech_server(monkeypatch, handler):
            source = PcmFixture()
            live = LiveSpeechInput({"asr_attempts": 2}, source)
            with pytest.raises(OSError, match="重连次数"):
                await live.listen(1)
            await live.aclose()
            assert len(connections) == 2
            assert source.closed

    asyncio.run(scenario())


def test_pause_during_backpressure_drains_and_reconnects_only_new_audio(
    monkeypatch,
):
    """旧发送被背压卡住时暂停必须撤销旧任务，恢复后不能提交旧帧。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        blocked = asyncio.Event()
        frames, sockets = [], []
        original_send = ClientConnection.send
        blocked_once = False

        async def send(socket, message, *args, **kwargs):
            """只阻塞一次真实客户端音频发送，控制消息仍走原生socket。"""
            nonlocal blocked_once
            if isinstance(message, bytes) and not blocked_once:
                blocked_once = True
                blocked.set()
                await asyncio.Event().wait()
            return await original_send(socket, message, *args, **kwargs)

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            await acknowledge(socket)
            sockets.append(socket)
            async for frame in socket:
                frames.append(frame)

        monkeypatch.setattr(ClientConnection, "send", send)
        async with speech_server(monkeypatch, handler):
            source = PcmFixture()
            live = LiveSpeechInput({}, source)
            try:
                assert await live.listen(0.03) is None
                await asyncio.wait_for(blocked.wait(), 1)
                before = source.frames
                await until(lambda: source.frames >= before + 4)
                live.pause()
                await until(lambda: bool(frames))
                assert frames[-1] == bytes(3200)
                assert len(sockets) == 2
                live.resume()
                resume_frame = source.frames
                await until(lambda: frames[-1] != bytes(3200))
                assert int.from_bytes(frames[-1][:2], "little") > resume_frame
                assert len(sockets) == 2
            finally:
                await live.aclose()
            assert source.closed

    asyncio.run(scenario())


def test_accepted_final_resets_budget_but_preserves_pause_across_reconnect(
    monkeypatch,
):
    """只有实际交付最终句重置失败预算，重连期间暂停继续发送静音。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        sockets, frames = [], []
        disconnect = asyncio.Event()

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            command = await acknowledge(socket)
            sockets.append(socket)
            if len(sockets) == 2:
                await final(socket, command, "有效句")
                await disconnect.wait()
            if len(sockets) == 3:
                frames.append(await socket.recv())
            await socket.close()

        async with speech_server(monkeypatch, handler):
            source = PcmFixture()
            live = LiveSpeechInput({"asr_attempts": 2}, source)
            try:
                assert await live.listen(1) == "有效句"
                disconnect.set()
                with pytest.raises(OSError, match="重连次数"):
                    await live.listen(1)
            finally:
                await live.aclose()
            assert len(sockets) == 3
            assert frames == [bytes(3200)]
            assert source.closed

    asyncio.run(scenario())


def test_invalid_final_flags_fail_once_instead_of_delivering_text(monkeypatch):
    """外部事件的布尔字段必须严格校验，不能把字符串当作最终句。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        connections = []

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            command = await acknowledge(socket)
            connections.append(socket)
            await event(
                socket,
                command,
                "result-generated",
                {
                    "output": {
                        "sentence": {
                            "sentence_end": "yes",
                            "text": "错误句",
                            "begin_time": 0,
                        }
                    },
                },
            )
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler):
            source = PcmFixture()
            live = LiveSpeechInput({}, source)
            try:
                with pytest.raises(OSError, match="最终句无效"):
                    await live.listen(1)
            finally:
                await live.aclose()
            assert len(connections) == 1
            assert source.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "phase", ["connect", "handshake", "send", "pcm", "receive"]
)
def test_cancel_listen_releases_all_owned_io(monkeypatch, phase):
    """取消在途等待必须回收连接和PCM，不能留下后台原始操作。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        entered = asyncio.Event()
        original_send = client.ClientConnection.send

        class WaitingPcm(PcmFixture):
            """只在PCM场景保持读取在途。"""

            async def read(self, size, timeout=0.2):
                """可控PCM等待，不涉及真实硬件。"""
                if phase == "pcm":
                    entered.set()
                    await asyncio.Event().wait()
                return await super().read(size, timeout)

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            if phase == "handshake":
                await socket.recv()
                entered.set()
                await socket.wait_closed()
                return
            await acknowledge(socket)
            if phase == "receive":
                entered.set()
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler) as network:
            routed_connect = client.connect

            async def connect(uri, **kwargs):
                """控制原生连接建立前的网络等待。"""
                if phase == "connect":
                    entered.set()
                    await asyncio.Event().wait()
                return await routed_connect(uri, **kwargs)

            async def send(socket, message, *args, **kwargs):
                """控制原生发送背压，关闭随后取消持有它的任务。"""
                if phase == "send" and isinstance(message, bytes):
                    entered.set()
                    await asyncio.Event().wait()
                return await original_send(socket, message, *args, **kwargs)

            network.setattr(client, "connect", connect)
            network.setattr(client.ClientConnection, "send", send)
            source = WaitingPcm()
            live = LiveSpeechInput({}, source)
            listening = asyncio.create_task(live.listen(10))
            await asyncio.wait_for(entered.wait(), 1)
            listening.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(listening, 1)
            await live.aclose()
            assert source.closed
            assert await live.listen(0.01) is None

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["capture", "send", "receive", "close"])
def test_programming_errors_surface_after_resource_cleanup(
    monkeypatch, operation
):
    """编程异常原样显露，不伪装成普通网络失败或遗漏其余资源。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        original_send = ClientConnection.send
        original_recv = ClientConnection.recv
        sockets = []

        class BrokenPcm(PcmFixture):
            """在外部设备操作中注入确定性的编程错误。"""

            async def read(self, size, timeout=0.2):
                """在网络握手完成后才触发采集错误。"""
                await until(lambda: bool(sockets))
                if operation == "capture":
                    raise RuntimeError("fixture programming error")
                return await super().read(size, timeout)

            async def aclose(self):
                """先完成设备回收再暴露关闭异常。"""
                await super().aclose()
                if operation == "close":
                    raise RuntimeError("fixture programming error")

        async def send(socket, message, *args, **kwargs):
            """握手控制消息不变，音频发送可注入编程错误。"""
            if operation == "send" and isinstance(message, bytes):
                raise RuntimeError("fixture programming error")
            return await original_send(socket, message, *args, **kwargs)

        async def recv(socket, *args, **kwargs):
            """握手之后接收可以暴露编程错误。"""
            if operation == "receive" and sockets:
                raise RuntimeError("fixture programming error")
            return await original_recv(socket, *args, **kwargs)

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            await acknowledge(socket)
            sockets.append(socket)
            await socket.wait_closed()

        monkeypatch.setattr(ClientConnection, "send", send)
        monkeypatch.setattr(ClientConnection, "recv", recv)
        async with speech_server(monkeypatch, handler):
            source = BrokenPcm()
            live = LiveSpeechInput({}, source)
            if operation == "close":
                assert await live.listen(0.03) is None
            else:
                with pytest.raises(RuntimeError, match="programming error"):
                    await live.listen(1)
            with pytest.raises(RuntimeError, match="programming error"):
                await live.aclose()
            assert source.closed
            assert all(socket.state.name == "CLOSED" for socket in sockets)

    asyncio.run(scenario())


def test_pcm_stall_fails_without_fake_silence_or_network_retry(monkeypatch):
    """缺少真实PCM必须停止接入，不能伪造静音掩盖故障。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        connections, frames = [], []

        class SilentPcm(PcmFixture):
            """持续无数据的设备，只按读取期限返回None。"""

            async def read(self, size, timeout=0.2):
                """有限等待保持事件循环可响应。"""
                await asyncio.sleep(timeout)
                return None

        async def handler(socket):
            """本机语音服务器提供可控事件并等待连接释放。"""
            await acknowledge(socket)
            connections.append(socket)
            async for frame in socket:
                frames.append(frame)

        async with speech_server(monkeypatch, handler):
            source = SilentPcm()
            live = LiveSpeechInput({"speech_timeout": 0.06}, source)
            with pytest.raises(OSError, match="PCM采集超时"):
                await live.listen(1)
            await live.aclose()
            assert len(connections) == 1
            assert frames == []
            assert source.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("status, expected_attempts", [(401, 1), (503, 2)])
def test_http_authentication_and_transient_failures_have_distinct_budget(
    monkeypatch, status, expected_attempts
):
    """鉴权失败立刻停止；明确的暂时HTTP故障才使用连续网络预算。"""

    async def scenario():
        """在同一事件循环观察输入、错误及资源回收。"""
        attempts = []

        async def reject(socket, request):
            """在真实HTTP升级处拒绝无效fixture凭证。"""
            attempts.append(request)
            return socket.respond(status, "fixture rejection")

        async def handler(socket):
            """拒绝升级后不允许启动语音任务。"""
            raise AssertionError("拒绝的连接不能启动任务")

        async with speech_server(monkeypatch, handler, process_request=reject):
            source = PcmFixture()
            live = LiveSpeechInput({}, source)
            try:
                with pytest.raises(OSError):
                    await live.listen(1)
            finally:
                await live.aclose()
            assert len(attempts) == expected_attempts
            assert source.closed

    asyncio.run(scenario())


def test_duplicate_final_cannot_be_delivered_again_after_immediate_resume(
    monkeypatch,
):
    """即使尚未发送下一帧，恢复也不能再次交付同一服务端最终句。"""

    async def scenario():
        """用延迟PCM控制最终句与恢复之间没有发送进度的时段。"""
        sockets = []

        class DelayedPcm(PcmFixture):
            """保持第一帧在途，使重复事件落在相同音频时刻。"""

            async def read(self, size, timeout=0.2):
                """最终句来自已确定的服务端测试事件，不伪造PCM数据。"""
                await asyncio.sleep(0.1)
                return None

        async def handler(socket):
            """先交付最终句，然后等待调用者发送重复事件。"""
            command = await acknowledge(socket)
            sockets.append((socket, command))
            await final(socket, command, "同一句", 0)
            await socket.wait_closed()

        async with speech_server(monkeypatch, handler):
            source = DelayedPcm()
            live = LiveSpeechInput({}, source)
            try:
                assert await live.listen(1) == "同一句"
                live.resume()
                socket, command = sockets[0]
                await final(socket, command, "同一句", 0)
                assert await live.listen(0.03) is None
            finally:
                await live.aclose()

    asyncio.run(scenario())
