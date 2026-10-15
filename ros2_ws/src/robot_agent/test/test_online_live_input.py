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
