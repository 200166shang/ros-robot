"""通过语音输入验证真实协议 Adapter，固定传输事件不代替云端验收。"""

import json
import queue
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest
import websocket

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.conversation.interaction import OnlineInteraction
from robot_agent.voice.session import OnlineVoice
from robot_agent.voice.speech import DashScopeASR, DashScopeTTS


class FixedModel:
    """从固定识别文本生成确定的普通聊天。"""

    def complete(self, text, timeout):
        """输入原样出现在回复中，便于检测中间句或重复句。"""
        return json.dumps({"function": [], "response": text})


class SpeechSocket:
    """固定服务端事件的传输替身，保留真实任务构造和音频发送。"""

    def __init__(self, fail=False, tts_fail=False):
        """初始化事件队列和连接失败模式。"""
        self.queue = queue.Queue()
        self.fail = fail
        self.tts_fail = tts_fail
        self.task_id = ""
        self.kind = ""
        self.frames = []
        self.closed = False
        self.commands = []

    def settimeout(self, timeout):
        """固定传输使用短轮询期限。"""

    def event(self, kind, payload=None):
        """返回当前任务的固定事件。"""
        self.queue.put(
            json.dumps(
                {
                    "header": {"event": kind, "task_id": self.task_id},
                    "payload": payload or {},
                }
            )
        )

    def send(self, raw):
        """接纳真实控制命令并返回确定服务端响应。"""
        command = json.loads(raw)
        self.commands.append(command)
        action = command["header"]["action"]
        self.task_id = command["header"]["task_id"]
        if action == "run-task":
            self.kind = command["payload"]["task"]
            self.event("task-started")
            if self.fail:
                self.event("task-failed")
        if action == "finish-task":
            if self.kind == "asr":
                for text, final, heartbeat in [
                    ("中间文本", False, False),
                    ("保活文本", True, True),
                    ("真实句一。", True, False),
                    ("真实句二。", True, False),
                ]:
                    self.event(
                        "result-generated",
                        {
                            "output": {
                                "sentence": {
                                    "text": text,
                                    "sentence_end": final,
                                    "heartbeat": heartbeat,
                                }
                            }
                        },
                    )
            elif self.tts_fail:
                self.queue.put(b"partial audio")
                self.event("task-failed")
                return
            else:
                self.queue.put(bytes(3200))
                self.queue.put(bytes(1600))
            self.event("task-finished")

    def send_binary(self, frame):
        """记录 PCM 帧，验证暂停期间仅有静音且没有消费源音频。"""
        self.frames.append(frame)

    def recv(self):
        """等待事件并按传输契约报告短轮询超时。"""
        try:
            return self.queue.get(timeout=0.01)
        except queue.Empty:
            raise websocket.WebSocketTimeoutException()

    def close(self, timeout=None):
        """记录连接释放，退出唤醒等待者。"""
        self.closed = True


def fixture_wav(tmp_path):
    """构造一帧非静音 PCM 输入，避免测试依赖外部录音。"""
    path = tmp_path / "input.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 1600)
    return path


def transport(monkeypatch, sockets):
    """固定外部传输；凭证只进入请求头，测试不输出。"""
    pending = iter(sockets)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    def connect(endpoint, header, timeout):
        """每次连接返回新任务通道。"""
        assert endpoint.startswith("wss://")
        return next(pending)

    monkeypatch.setattr(websocket, "create_connection", connect)


def test_reconnect_final_sentences_and_streaming_audio(tmp_path, monkeypatch):
    """识别断线重连；仅最终句进入模型；TTS流式音频保存成有效WAV。"""
    sockets = [SpeechSocket(fail=True), SpeechSocket(), SpeechSocket()]
    transport(monkeypatch, sockets)
    asr = DashScopeASR({})
    voice = OnlineVoice(
        OnlineInteraction(FixedModel(), create_default_actions().registry),
        asr,
        DashScopeTTS({}),
        tmp_path,
        music_playing=lambda: False,
        recognize_recording=asr.recognize,
        retry_delay=0,
    )
    result = voice.submit_recording(fixture_wav(tmp_path))
    assert result["transcript"] == "真实句一。真实句二。"
    assert result["reply"] == result["transcript"]
    assert result["tts_status"] == "completed"
    with wave.open(result["audio_path"]) as audio:
        assert audio.getframerate() == 16000
        assert audio.getnframes() == 2400
    assert sockets[1].frames == [b"\x01\x00" * 1600]
    assert all(socket.closed for socket in sockets)
    assert (
        sockets[2].commands[1]["payload"]["input"]["text"] == result["reply"]
    )
    voice.close()


def test_pause_keepalive_resume_preserves_audio(tmp_path, monkeypatch):
    """暂停时只发静音保活，恢复后原音频完整发送并关闭连接。"""
    socket = SpeechSocket()
    transport(monkeypatch, [socket])
    asr = DashScopeASR({})
    asr.pause()
    with ThreadPoolExecutor() as executor:
        result = executor.submit(asr.recognize, fixture_wav(tmp_path), 2)
        deadline = time.monotonic() + 1
        while len(socket.frames) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert socket.frames == [bytes(3200)] * 2
        asr.resume()
        assert result.result(timeout=2) == "真实句一。真实句二。"
    assert socket.frames[-1] == b"\x01\x00" * 1600
    assert socket.closed
    asr.close()


def test_partial_tts_failure_has_no_success_audio(tmp_path, monkeypatch):
    """合成返回部分音频后失败，回合仍返回文本且删除临时音频。"""
    sockets = [SpeechSocket(), SpeechSocket(tts_fail=True)]
    transport(monkeypatch, sockets)
    asr = DashScopeASR({})
    voice = OnlineVoice(
        OnlineInteraction(FixedModel(), create_default_actions().registry),
        asr,
        DashScopeTTS({}),
        tmp_path,
        music_playing=lambda: False,
        recognize_recording=asr.recognize,
        tts_attempts=1,
    )
    result = voice.submit_recording(fixture_wav(tmp_path))
    assert result["tts_status"] == "failed"
    assert "audio_path" not in result
    assert list(tmp_path.glob("*.tmp")) == []
    assert voice.state == "standby"
    assert all(socket.closed for socket in sockets)


def test_recognition_timeout_is_bounded_and_releases_connection(
    tmp_path, monkeypatch
):
    """识别暂停超过期限时不永久阻塞，也不在关闭后自动重连。"""
    sockets = [SpeechSocket(), SpeechSocket()]
    transport(monkeypatch, sockets)
    asr = DashScopeASR({})
    asr.pause()
    with pytest.raises(OSError):
        asr.recognize(fixture_wav(tmp_path), 0.1)
    assert sockets[0].closed
    asr.close()
    with pytest.raises(OSError):
        asr.recognize(tmp_path / "input.wav", 0.1)


def test_tts_transport_send_error_is_compatible(tmp_path, monkeypatch):
    """文本传输失败转换为业务错误，仍释放连接且不提交音频。"""

    class BrokenTextSocket(SpeechSocket):
        """在真实文本提交阶段模拟连接中断。"""

        def send(self, raw):
            """握手成功后拒绝文本发送。"""
            if json.loads(raw)["header"]["action"] == "continue-task":
                raise websocket.WebSocketConnectionClosedException("broken")
            super().send(raw)

    socket = BrokenTextSocket()
    transport(monkeypatch, [socket])
    destination = tmp_path / "reply.wav"
    with pytest.raises(OSError):
        DashScopeTTS({}).synthesize("你好", destination, 1)
    assert socket.closed
    assert not destination.exists()
    assert not destination.with_suffix(".wav.tmp").exists()


@pytest.mark.parametrize("operation", ["asr", "tts"])
def test_late_connection_does_not_start_expired_task(
    tmp_path, monkeypatch, operation
):
    """建立连接耗尽总期限时释放迟到连接，不再提交任务。"""
    socket = SpeechSocket()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    def connect(*args, **kwargs):
        """模拟连接在调用期限后才返回。"""
        time.sleep(0.03)
        return socket

    monkeypatch.setattr(websocket, "create_connection", connect)
    with pytest.raises(OSError):
        if operation == "asr":
            DashScopeASR({}).recognize(fixture_wav(tmp_path), 0.01)
        else:
            DashScopeTTS({}).synthesize("你好", tmp_path / "reply.wav", 0.01)
    assert socket.closed
    assert socket.commands == []


@pytest.mark.parametrize("failure", ["empty", "timeout", "wrong-task"])
def test_tts_requires_audio_and_matching_finish(
    tmp_path, monkeypatch, failure
):
    """无音频、未确认结束和其他任务的确认均不能提交成功 WAV。"""

    class IncompleteSocket(SpeechSocket):
        """在完成请求后只返回指定的不完整合成结果。"""

        def send(self, raw):
            """保留真实握手与文本请求，仅控制外部完成事件。"""
            command = json.loads(raw)
            if command["header"]["action"] != "finish-task":
                return super().send(raw)
            self.commands.append(command)
            if failure == "empty":
                self.event("task-finished")
            else:
                self.queue.put(b"\x01\x00" * 1600)
                if failure == "wrong-task":
                    self.task_id = "another-task"
                    self.event("task-finished")

    socket = IncompleteSocket()
    transport(monkeypatch, [socket])
    destination = tmp_path / "reply.wav"
    with pytest.raises(OSError):
        DashScopeTTS({}).synthesize("你好", destination, 0.08)
    assert not destination.exists()
    assert not destination.with_suffix(".wav.tmp").exists()
    assert socket.closed


def test_retry_discards_failed_sentences_and_replays_audio(
    tmp_path, monkeypatch
):
    """部分最终句后断线，重试完整录音但不保留失败轮的识别句。"""

    class InterruptedSocket(SpeechSocket):
        """收完录音后先报告句子，再中断任务。"""

        def send(self, raw):
            """握手照常响应，结束输入后返回部分识别与断线。"""
            if json.loads(raw)["header"]["action"] != "finish-task":
                return super().send(raw)
            self.event(
                "result-generated",
                {
                    "output": {
                        "sentence": {
                            "text": "失败轮句子",
                            "sentence_end": True,
                        }
                    },
                },
            )
            self.queue.put("")

    sockets = [InterruptedSocket(), SpeechSocket()]
    transport(monkeypatch, sockets)
    assert DashScopeASR({}).recognize(fixture_wav(tmp_path), 2) == (
        "真实句一。真实句二。"
    )
    assert sockets[0].frames == sockets[1].frames == [b"\x01\x00" * 1600]
    assert sockets[0].task_id != sockets[1].task_id
    assert all(socket.closed for socket in sockets)
    for socket in sockets:
        assert all(
            command["header"]["task_id"] == socket.task_id
            for command in socket.commands
        )


@pytest.mark.parametrize("operation", ["asr", "tts"])
def test_close_during_connect_releases_late_connection(
    tmp_path, monkeypatch, operation
):
    """关闭正在建立的入口，迟到连接被回收且不会启动任务或重连。"""
    entered = threading.Event()
    release = threading.Event()
    socket = SpeechSocket()
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    def connect(*args, **kwargs):
        """连接建立由测试事件控制完成。"""
        entered.set()
        assert release.wait(2)
        return socket

    monkeypatch.setattr(websocket, "create_connection", connect)
    caller = DashScopeASR({}) if operation == "asr" else DashScopeTTS({})
    with ThreadPoolExecutor() as executor:
        if operation == "asr":
            result = executor.submit(
                caller.recognize, fixture_wav(tmp_path), 2
            )
        else:
            result = executor.submit(
                caller.synthesize, "你好", tmp_path / "reply.wav", 2
            )
        try:
            assert entered.wait(1)
            caller.close()
        finally:
            release.set()
        with pytest.raises(OSError):
            result.result(timeout=2)
    assert socket.closed
    assert socket.commands == []


@pytest.mark.parametrize("operation", ["asr", "tts"])
def test_programming_error_surfaces_after_release(
    tmp_path, monkeypatch, operation
):
    """意外编程错误不会变成默认成功或触发识别重试，连接仍回收。"""

    class BrokenSocket(SpeechSocket):
        """握手中报告非传输类错误。"""

        def recv(self):
            """暴露意外的内部错误。"""
            raise RuntimeError("programming error")

    socket = BrokenSocket()
    transport(monkeypatch, [socket])
    with pytest.raises(RuntimeError, match="programming error"):
        if operation == "asr":
            DashScopeASR({}).recognize(fixture_wav(tmp_path), 1)
        else:
            DashScopeTTS({}).synthesize("你好", tmp_path / "reply.wav", 1)
    assert socket.closed


@pytest.mark.parametrize("channels,frames", [(2, 1600), (1, 0)])
def test_wav_validation_precedes_connection(
    tmp_path, monkeypatch, channels, frames
):
    """无效格式和空录音在接入网络前被拒绝。"""
    transport(monkeypatch, [])
    path = tmp_path / "invalid.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setparams((channels, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(frames * channels * 2))
    with pytest.raises(ValueError):
        DashScopeASR({}).recognize(path, 1)


def test_tts_close_failure_still_removes_partial_audio(tmp_path, monkeypatch):
    """部分合成失败后，即使关闭传输也失败，临时音频仍被清理。"""

    class BrokenCloseSocket(SpeechSocket):
        """模拟清理阶段的传输关闭错误。"""

        def close(self, timeout=None):
            """记录已尝试释放后报告传输错误。"""
            super().close(timeout)
            raise websocket.WebSocketConnectionClosedException("closed")

    socket = BrokenCloseSocket(tts_fail=True)
    transport(monkeypatch, [socket])
    destination = tmp_path / "reply.wav"
    with pytest.raises(OSError):
        DashScopeTTS({}).synthesize("你好", destination, 1)
    assert socket.closed
    assert not destination.exists()
    assert not destination.with_suffix(".wav.tmp").exists()
