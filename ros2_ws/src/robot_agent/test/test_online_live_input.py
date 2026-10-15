"""在PCM与WSS真实Seam验证持续输入、暂停保活及迟到句过滤。"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import websocket
from test_online_speech import SpeechSocket, transport

from robot_agent.voice.live_input import LiveSpeechInput


class PcmFixture:
    """按固定节奏产出可辨认PCM帧，关闭可取消读取。"""

    def __init__(self):
        """保存设备生命周期与清理回执。"""
        self.closed = threading.Event()
        self.discarded = threading.Event()
        self.frames = 0

    def start(self):
        """固定设备无需外部资源。"""

    def read(self, size, timeout=0.2):
        """产出非静音；暂停时仍必须持续消费。"""
        if self.closed.wait(0.02):
            return None
        self.frames += 1
        return b"\x01\x00" * (size // 2)

    def discard(self):
        """向测试回执恢复前的音频积压已经清理。"""
        self.discarded.set()

    def close(self):
        """取消在途读取。"""
        self.closed.set()


def until(predicate):
    """只等待公开设备回执，避免线程时序依赖固定睡眠。"""
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.005)


def final(socket, text, begin):
    """提供带音频时间戳的最终句。"""
    socket.event(
        "result-generated",
        {
            "output": {
                "sentence": {
                    "text": text,
                    "begin_time": begin,
                    "sentence_end": True,
                    "heartbeat": False,
                }
            }
        },
    )


def test_live_pause_drains_mic_keeps_connection_and_filters_late_sentence(
    monkeypatch,
):
    """一条任务跨越多轮，暂停丢弃真实音频且恢复不交付旧句。"""
    socket, source = SpeechSocket(), PcmFixture()
    transport(monkeypatch, [socket])
    live = LiveSpeechInput({}, source)
    try:
        assert live.listen(0.02) is None
        until(lambda: len(socket.frames) >= 2)
        socket.event(
            "result-generated",
            {
                "output": {
                    "sentence": {
                        "text": "中间句",
                        "sentence_end": False,
                    }
                }
            },
        )
        socket.event(
            "result-generated",
            {
                "output": {
                    "sentence": {
                        "text": "心跳",
                        "sentence_end": True,
                        "heartbeat": True,
                    }
                }
            },
        )
        assert live.listen(0.03) is None
        final(socket, "第一句", 0)
        assert live.listen(1) == "第一句"
        baseline = len(socket.frames)
        until(lambda: len(socket.frames) >= baseline + 3)
        assert socket.frames[-2:] == [bytes(3200)] * 2
        assert source.frames > baseline
        final(socket, "播报泄漏", 0)
        assert live.listen(0.05) is None
        live.resume()
        assert source.discarded.wait(1)
        final(socket, "迟到旧句", 0)
        assert live.listen(0.05) is None
        final(socket, "第二句", len(socket.frames) * 100)
        assert live.listen(1) == "第二句"
        assert len(socket.commands) == 1
        assert socket.commands[0]["payload"]["parameters"]["heartbeat"]
        assert not socket.closed
    finally:
        live.close()
    assert socket.closed and source.closed.is_set()


def test_live_reconnect_does_not_replay_and_exhaustion_is_visible(monkeypatch):
    """失败任务不交付句子；重连有界，耗尽明确失败且回收设备。"""
    first, second = SpeechSocket(fail=True), SpeechSocket()
    third = SpeechSocket(fail=True)
    transport(monkeypatch, [first, second, third])
    source = PcmFixture()
    live = LiveSpeechInput({"asr_attempts": 2}, source)
    try:
        live.listen(0.02)
        until(lambda: bool(second.frames))
        assert first.closed
        final(second, "恢复后的输入", 0)
        assert live.listen(1) == "恢复后的输入"
        second.event("task-failed")
        # 有效句重置连续失败计数，第二次失败耗尽重连预算。
        with pytest.raises(OSError, match="重连次数"):
            while True:
                live.listen(0.1)
    finally:
        live.close()
    assert source.closed.is_set()


def test_live_close_cancels_idle_listen_and_pcm_read(monkeypatch):
    """无人说话也能关闭，不等待整句超时或遗留采集线程。"""
    socket, source = SpeechSocket(), PcmFixture()
    transport(monkeypatch, [socket])
    live = LiveSpeechInput({}, source)
    live.listen(0.02)
    until(lambda: bool(socket.frames))
    before = time.monotonic()
    live.close()
    assert time.monotonic() - before < 1
    assert live.listen(0.02) is None
    assert source.closed.is_set() and socket.closed


def test_pcm_failure_stops_input_without_network_replay(monkeypatch):
    """设备错误不重开ASR任务，更不能把缺失音频当作静音成功。"""

    class FailingPcm(PcmFixture):
        """显式触发真实设备读取失败。"""

        failed = False

        def read(self, size, timeout=0.2):
            """读取失败经公共listen显露。"""
            if self.failed:
                raise OSError("PCM device failed")
            return super().read(size, timeout)

    socket, source = SpeechSocket(), FailingPcm()
    transport(monkeypatch, [socket])
    live = LiveSpeechInput({}, source)
    try:
        live.listen(0.02)
        until(lambda: bool(socket.frames))
        source.failed = True
        with pytest.raises(OSError, match="PCM device failed"):
            while True:
                live.listen(0.1)
    finally:
        live.close()
    assert socket.closed and source.closed.is_set()


def test_close_during_connection_creation_releases_late_socket(monkeypatch):
    """关闭遇到尚未返回的连接时，迟到socket仍须被关闭且不启动任务。"""
    opened, release = threading.Event(), threading.Event()
    socket, source = SpeechSocket(), PcmFixture()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    def connect(*args, **kwargs):
        """模拟握手I/O尚未返回，外部网络等待有界。"""
        opened.set()
        assert release.wait(1)
        return socket

    monkeypatch.setattr(websocket, "create_connection", connect)
    live = LiveSpeechInput({}, source)
    live.listen(0.02)
    assert opened.wait(1)
    try:
        with ThreadPoolExecutor() as executor:
            closing = executor.submit(live.close)
            release.set()
            closing.result(timeout=2)
    finally:
        release.set()
        live.close()
    assert socket.closed
    assert socket.commands == []


@pytest.mark.parametrize("failing_resource", ["socket", "source"])
def test_close_failure_still_releases_other_resources(
    monkeypatch, failing_resource
):
    """关闭步骤出现编程异常时，其余设备回收仍必须执行并显露错误。"""

    class ClosingSocket(SpeechSocket):
        """在传输资源Seam注入关闭异常。"""

        def close(self, timeout=None):
            """标记真实关闭后抛出可观察的编程错误。"""
            super().close(timeout)
            if failing_resource == "socket":
                raise RuntimeError("cleanup failure")

    class ClosingSource(PcmFixture):
        """在设备资源Seam注入关闭异常。"""

        def close(self):
            """设备仍需取消读取，再向调用者显露错误。"""
            super().close()
            if failing_resource == "source":
                raise RuntimeError("cleanup failure")

    socket, source = ClosingSocket(), ClosingSource()
    transport(monkeypatch, [socket])
    live = LiveSpeechInput({}, source)
    live.listen(0.02)
    until(lambda: bool(socket.frames))
    with pytest.raises(RuntimeError, match="cleanup failure"):
        live.close()
    assert socket.closed and source.closed.is_set()


@pytest.mark.parametrize("operation", ["send", "receive"])
@pytest.mark.parametrize("programming_error", [False, True])
def test_live_transport_failure_is_visible_and_releases_pcm(
    monkeypatch, operation, programming_error
):
    """传输失败有限重连；编程错误原样显露且不遗漏设备清理。"""

    class FailingSocket(SpeechSocket):
        """在已握手的传输操作中注入可控错误。"""

        def send_binary(self, frame):
            """模拟发送失败，不把失败帧记录为成功。"""
            if operation == "send":
                self.fail_operation()
            super().send_binary(frame)

        def recv(self):
            """握手成功后才触发接收失败。"""
            if operation == "receive" and self.queue.empty():
                self.fail_operation()
            return super().recv()

        def fail_operation(self):
            """网络异常由任务转换，编程异常必须保留原类型。"""
            if programming_error:
                raise RuntimeError("transport programming error")
            raise websocket.WebSocketConnectionClosedException("disconnected")

    socket, source = FailingSocket(), PcmFixture()
    transport(monkeypatch, [socket])
    live = LiveSpeechInput({"asr_attempts": 1}, source)
    expected = RuntimeError if programming_error else OSError
    message = (
        "transport programming error" if programming_error else "重连次数"
    )
    try:
        with pytest.raises(expected, match=message):
            while True:
                live.listen(0.1)
    finally:
        if programming_error:
            with pytest.raises(RuntimeError, match=message):
                live.close()
        else:
            live.close()
    assert socket.closed and source.closed.is_set()
    assert len(socket.commands) == 1


@pytest.mark.parametrize("operation", ["send", "receive", "pcm"])
def test_close_cancels_inflight_io(monkeypatch, operation):
    """关闭可取消在途发送、接收或PCM读取，所有线程均有界结束。"""
    entered, released = threading.Event(), threading.Event()

    class BlockingSocket(SpeechSocket):
        """等待关闭回执的外部传输替身。"""

        def send_binary(self, frame):
            """让发送停留在外部I/O中，直到关闭取消。"""
            if operation == "send":
                entered.set()
                assert released.wait(2)
                raise websocket.WebSocketConnectionClosedException("closed")
            super().send_binary(frame)

        def recv(self):
            """先完成握手，再阻塞事件接收。"""
            if operation == "receive" and self.queue.empty():
                entered.set()
                assert released.wait(2)
                raise websocket.WebSocketConnectionClosedException("closed")
            return super().recv()

        def close(self, timeout=None):
            """释放外部I/O等待者。"""
            super().close(timeout)
            released.set()

    class BlockingPcm(PcmFixture):
        """提供等待设备关闭的PCM读取。"""

        def read(self, size, timeout=0.2):
            """外部关闭取消读取，不伪造采集成功。"""
            if operation == "pcm":
                entered.set()
                assert self.closed.wait(2)
                return None
            return super().read(size, timeout)

    socket, source = BlockingSocket(), BlockingPcm()
    transport(monkeypatch, [socket])
    live = LiveSpeechInput({}, source)
    try:
        with ThreadPoolExecutor() as executor:
            listening = executor.submit(live.listen, 1)
            assert entered.wait(1)
            until(lambda: bool(socket.commands))
            live.close()
            assert listening.result(timeout=1) is None
        assert live.listen(0.01) is None
    finally:
        released.set()
        live.close()
    assert source.closed.is_set() and socket.closed


def test_missing_pcm_times_out_without_silence_success(monkeypatch):
    """采集持续无数据必须显露超时，不能用静音冒充正常保活。"""

    class EmptyPcm(PcmFixture):
        """只报告轮询无数据的采集替身。"""

        def read(self, size, timeout=0.2):
            """模拟有界读取始终拿不到完整PCM帧。"""
            self.closed.wait(0.01)
            return None

    socket, source = SpeechSocket(), EmptyPcm()
    transport(monkeypatch, [socket])
    live = LiveSpeechInput({"speech_timeout": 0.05}, source)
    try:
        with pytest.raises(OSError, match="PCM采集超时"):
            while True:
                live.listen(0.1)
    finally:
        live.close()
    assert socket.frames == []
    assert len(socket.commands) == 1
    assert socket.closed and source.closed.is_set()


def test_live_reconnect_sends_only_new_capture(monkeypatch):
    """发送失败后只发新采集帧，不能重放上一任务已消费的音频。"""

    class NumberedPcm(PcmFixture):
        """每帧内容标记采集次序，便于观察重放。"""

        def read(self, size, timeout=0.2):
            """按公开PCM读取契约返回唯一帧。"""
            frame = super().read(size, timeout)
            if frame is None:
                return None
            return self.frames.to_bytes(2, "little") * (size // 2)

    class InterruptedSocket(SpeechSocket):
        """第二帧发送发生断线，前一帧已经提交。"""

        def send_binary(self, frame):
            """记录已尝试发送的音频，包括结果未知的失败帧。"""
            super().send_binary(frame)
            if len(self.frames) == 2:
                raise websocket.WebSocketConnectionClosedException("lost")

    first, second = InterruptedSocket(), SpeechSocket()
    source = NumberedPcm()
    transport(monkeypatch, [first, second])
    live = LiveSpeechInput({}, source)
    try:
        live.listen(0.02)
        until(lambda: len(second.frames) >= 2)
        final(second, "断线后新句", 0)
        assert live.listen(1) == "断线后新句"
        assert len(first.frames) == 2
        assert all(frame not in first.frames for frame in second.frames[:2])
        assert len(first.commands) == len(second.commands) == 1
        assert first.closed
    finally:
        live.close()
    assert second.closed and source.closed.is_set()
