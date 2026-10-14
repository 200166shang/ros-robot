"""从语音交互 Interface 观察会话状态、可信回复与音频回执。"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from robot_agent.online_actions import ActionHandler, ActionRegistry
from robot_agent.online_interaction import OnlineInteraction
from robot_agent.online_voice import OnlineVoice


class FixedSpeech:
    """提供固定识别事件，并记录公开采集生命周期。"""

    def __init__(self):
        """初始化可控文本与连接事件。"""
        self.text = "请点头"
        self.events = []

    def recognize(self, path, timeout):
        """只在录音提交时返回固定识别文本。"""
        self.events.append("recognize")
        return self.text

    def pause(self):
        """记录半双工暂停。"""
        self.events.append("pause")

    def resume(self):
        """记录半双工恢复。"""
        self.events.append("resume")

    def close(self):
        """记录连接关闭。"""
        self.events.append("close")


class FixedModel:
    """返回动作建议，成功承诺由真实动作回执替代。"""

    def __init__(self):
        """初始化输入记录与建议动作。"""
        self.inputs = []
        self.functions = ["head_nod"]

    def complete(self, text, timeout):
        """记录用户输入并模拟分片模型响应。"""
        self.inputs.append(text)
        raw = json.dumps({"function": self.functions, "response": "已经好了"})
        return iter([raw[:12], raw[12:]])


class FixedTTS:
    """记录实际交给合成器的回复，可指定失败次数。"""

    def __init__(self):
        """初始化回复记录。"""
        self.replies = []
        self.failures = 0

    def synthesize(self, text, destination, timeout):
        """保存固定音频替身，仅用于行为测试。"""
        self.replies.append(text)
        if self.failures:
            self.failures -= 1
            raise OSError("temporary provider failure")
        destination.write_bytes(b"audio fixture")

    def close(self):
        """固定合成器没有外部资源。"""


def make_voice(tmp_path, **settings):
    """组装真实交互与模拟设备，替换在线输入与合成 Adapter。"""
    speech, model, tts = FixedSpeech(), FixedModel(), FixedTTS()
    actions = ActionRegistry()
    voice = OnlineVoice(
        OnlineInteraction(model, actions),
        speech,
        tts,
        tmp_path,
        music_playing=lambda: actions.music.is_playing,
        retry_delay=0,
        **settings,
    )
    return voice, speech, model, tts


def test_recording_bypasses_wake_and_speaks_confirmed_result(tmp_path):
    """录音直接单回合；合成可信动作回执并关联文本与音频。"""
    voice, speech, model, tts = make_voice(tmp_path)
    result = voice.submit_recording(tmp_path / "input.wav")
    assert result["transcript"] == "请点头"
    assert result["actions"][0]["status"] == "simulated_success"
    assert "模拟成功" in tts.replies[0]
    assert "已经好了" not in tts.replies[0]
    assert result["tts_status"] == "completed"
    assert speech.events == ["recognize", "pause", "resume"]
    assert voice.state == "standby"
    saved = json.loads((tmp_path / (result["turn_id"] + ".json")).read_text())
    assert saved == result


def test_session_wake_continuity_sleep_and_silence(tmp_path):
    """同音唤醒后连续交互，子串不触发休眠，精确指令和静音回待机。"""
    now = [0.0]
    voice, speech, model, tts = make_voice(tmp_path, clock=lambda: now[0])
    assert voice.submit_transcript("你好")["status"] == "ignored"
    for name in ("小沫", "小莫", "小墨", "小末", "小陌", "小默"):
        assert voice.submit_transcript(name + "，" + name)["status"] == "woken"
        assert voice.state == "listening"
        assert (
            voice.submit_transcript("好了以后请点头")["status"] == "completed"
        )
        assert voice.submit_transcript("晚安。")["status"] == "sleeping"
        assert voice.state == "standby"
    voice.submit_transcript("小沫小沫")
    now[0] = 121
    voice.tick()
    assert voice.state == "standby"
    assert len(model.inputs) == 6


def test_music_filters_input_from_actual_simulation_state(tmp_path):
    """通过真实动作改变第二票音乐状态，再观察语音输入过滤和停止。"""
    voice, speech, model, tts = make_voice(tmp_path)
    voice.submit_transcript("小莫小莫")
    model.functions = ["play_music('夜曲')"]
    assert voice.submit_transcript("播放音乐")["status"] == "completed"
    assert voice.submit_transcript("今天的天气")["status"] == "filtered"
    model.functions = ["stop_music"]
    assert voice.submit_transcript("停止音乐")["status"] == "completed"
    assert voice.submit_transcript("今天的天气")["status"] == "completed"
    assert model.inputs == ["播放音乐", "停止音乐", "今天的天气"]


def test_tts_retry_degradation_and_explicit_recovery(tmp_path):
    """重试仅合成，连续失败降级；显式恢复不重复原动作。"""
    voice, speech, model, tts = make_voice(
        tmp_path, tts_attempts=2, failure_threshold=2
    )
    tts.failures = 1
    assert voice.submit_transcript("小沫小沫")["tts_status"] == "completed"
    tts.failures = 10
    assert voice.submit_transcript("请点头")["tts_status"] == "failed"
    assert voice.submit_transcript("请点头")["tts_status"] == "degraded"
    assert voice.submit_transcript("请点头")["tts_status"] == "disabled"
    assert len(model.inputs) == 3
    assert speech.events[-1] == "resume"
    voice.enable_tts()
    tts.failures = 0
    assert voice.submit_transcript("请点头")["tts_status"] == "completed"
    voice.close()
    assert voice.state == "closed"
    assert voice.submit_transcript("请点头")["status"] == "rejected"


def test_collecting_pauses_before_model_and_resumes_after_failure(tmp_path):
    """整个模型/动作/合成阶段暂停采集，合成异常仍能处理下一轮。"""
    voice, speech, model, tts = make_voice(tmp_path)
    original = model.complete

    def complete(text, timeout):
        """从 provider Adapter 观察半双工交接时序。"""
        assert speech.events[-1] == "pause"
        return original(text, timeout)

    model.complete = complete
    assert (
        voice.submit_recording(tmp_path / "input.wav")["status"] == "completed"
    )
    assert speech.events[-1] == "resume"


def test_asr_and_storage_failure_release_turn(tmp_path, monkeypatch):
    """识别失败不执行动作，记录写入异常也不会永久忙碌。"""
    voice, speech, model, tts = make_voice(tmp_path)
    original = speech.recognize

    def fail(path, timeout):
        """模拟一次在线识别失败。"""
        raise OSError("offline")

    speech.recognize = fail
    assert (
        voice.submit_recording(tmp_path / "input.wav")["asr_status"]
        == "failed"
    )
    assert model.inputs == []
    speech.recognize = original
    original_write = type(tmp_path).write_text

    def fail_write(path, *args, **kwargs):
        """模拟外部磁盘失败，必须让编程调用方观察异常。"""
        raise OSError("disk unavailable")

    monkeypatch.setattr(type(tmp_path), "write_text", fail_write)
    with pytest.raises(OSError):
        voice.submit_recording(tmp_path / "input.wav")
    assert voice.state == "standby"
    assert speech.events[-1] == "resume"
    monkeypatch.setattr(type(tmp_path), "write_text", original_write)
    assert (
        voice.submit_recording(tmp_path / "input.wav")["status"] == "completed"
    )


def test_busy_input_is_rejected_and_close_releases_adapters(tmp_path):
    """在途模型回合拒绝重叠；退出后不恢复已关闭的采集连接。"""
    voice, speech, model, tts = make_voice(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = model.complete

    def complete(text, timeout):
        """保持模型在途，允许从公共入口检查忙碌与退出。"""
        entered.set()
        release.wait(2)
        return original(text, timeout)

    model.complete = complete
    with ThreadPoolExecutor() as executor:
        turn = executor.submit(voice.submit_recording, tmp_path / "input.wav")
        assert entered.wait(1)
        assert voice.state == "processing"
        assert voice.submit_transcript("你好")["status"] == "busy"
        voice.close()
        release.set()
        assert turn.result(timeout=2)["tts_status"] == "disabled"
    assert speech.events[-1] == "close"
    assert voice.state == "closed"


def test_unknown_action_can_be_reconciled_without_reexecution(tmp_path):
    """语音入口保留既有迟到回执核对 Interface，不重发动作。"""
    speech, model, tts = FixedSpeech(), FixedModel(), FixedTTS()
    actions = ActionRegistry()
    release = threading.Event()
    finished = threading.Event()
    executions = []

    def nod(**parameters):
        """模拟迟到的确认回执，通过公开动作 Seam 控制设备结果。"""
        executions.append("nod")
        release.wait(2)
        finished.set()
        return {"status": "simulated_success", "detail": "迟到确认"}

    actions.register_many({"head_nod": ActionHandler(nod)})
    voice = OnlineVoice(
        OnlineInteraction(model, actions, action_timeout=0.01),
        speech,
        tts,
        tmp_path,
        music_playing=lambda: False,
    )
    result = voice.submit_recording(tmp_path / "input.wav")
    assert result["actions"][0]["status"] == "unknown"
    release.set()
    assert finished.wait(1)
    # 设备函数返回后 Future 才提交回执；公共核对可暂时返回仍未知。
    deadline = time.monotonic() + 1
    while True:
        reconciled = voice.reconcile(result["turn_id"])
        if reconciled["status"] == "completed":
            break
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert reconciled["transcript"] == "请点头"
    assert reconciled["tts_status"] == "completed"
    assert executions == ["nod"]
    assert (
        voice.submit_recording(tmp_path / "input.wav")["status"] == "completed"
    )


def test_filtered_input_does_not_extend_silence_and_playback_failure_recovers(
    tmp_path,
):
    """过滤不会无限维持唤醒；播放失败保留回复音频并释放回合。"""
    now = [0.0]

    def fail_playback(path):
        """模拟缺失播放设备。"""
        raise RuntimeError("device absent")

    voice, speech, model, tts = make_voice(
        tmp_path, clock=lambda: now[0], playback=fail_playback
    )
    voice.submit_transcript("小沫小沫")
    model.functions = ["play_music('夜曲')"]
    result = voice.submit_transcript("播放音乐")
    assert result["playback_status"] == "failed"
    assert result["tts_status"] == "completed"
    now[0] = 119
    assert voice.submit_transcript("天气")["status"] == "filtered"
    now[0] = 120
    assert voice.state == "standby"
