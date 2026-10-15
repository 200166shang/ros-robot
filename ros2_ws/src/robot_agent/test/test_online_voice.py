"""从语音交互 Interface 观察会话状态、可信回复与音频回执。"""

import asyncio
import json
import time
from pathlib import Path

import pytest

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.registry import ActionHandler
from robot_agent.application import AgentApplication
from robot_agent.conversation.agent import Agent
from robot_agent.results import ModelReply, ToolCall, result_to_json


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

    async def aclose(self):
        """记录连接关闭。"""
        self.events.append("close")


class FixedModel:
    """返回动作建议，成功承诺由真实动作回执替代。"""

    def __init__(self):
        """初始化输入记录与建议动作。"""
        self.inputs = []
        self.actions = [{"name": "head_nod", "arguments": {}}]

    async def complete(self, text, deadline, *, tools=None):
        """记录用户输入并返回完整模型响应。"""
        self.inputs.append(text)
        raw = ModelReply(
            "已经好了",
            ToolCall(
                "fixture_call", "execute_actions", {"actions": self.actions}
            )
            if self.actions
            else None,
        )
        return raw

    async def aclose(self):
        """固定模型没有本地连接资源。"""
        pass


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
    capabilities = create_default_actions()
    actions = capabilities.registry
    voice = AgentApplication(
        Agent(model, actions),
        speech,
        tts,
        tmp_path,
        music_playing=capabilities.music_playing,
        recognize_recording=lambda path, timeout: speech.recognize(
            path, timeout
        ),
        retry_delay=0,
        **settings,
    )
    return voice, speech, model, tts


def test_recording_bypasses_wake_and_speaks_confirmed_result(tmp_path):
    """录音直接单回合；合成可信动作回执并关联文本与音频。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(tmp_path)
        result = await voice.submit_recording(tmp_path / "input.wav")
        assert result.transcript == "请点头"
        assert result.actions[0].status == "simulated_success"
        assert "模拟成功" in tts.replies[0]
        assert "已经好了" not in tts.replies[0]
        assert result.tts_status == "completed"
        assert speech.events == ["recognize", "pause", "resume"]
        assert voice.state == "standby"
        saved = json.loads((tmp_path / (result.turn_id + ".json")).read_text())
        assert saved == result_to_json(result)

    asyncio.run(scenario())


def test_session_wake_continuity_sleep_and_silence(tmp_path):
    """同音唤醒后连续交互，子串不触发休眠，精确指令和静音回待机。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        now = [0.0]
        voice, speech, model, tts = make_voice(tmp_path, clock=lambda: now[0])
        assert (await voice.submit_transcript("你好")).status == "ignored"
        for name in ("小沫", "小莫", "小墨", "小末", "小陌", "小默"):
            assert (
                await voice.submit_transcript(name + "，" + name)
            ).status == "woken"
            assert voice.state == "listening"
            assert (
                await voice.submit_transcript("好了以后请点头")
            ).status == "completed"
            assert (
                await voice.submit_transcript("晚安。")
            ).status == "sleeping"
            assert voice.state == "standby"
        (await voice.submit_transcript("小沫小沫"))
        now[0] = 121
        voice.tick()
        assert voice.state == "standby"
        assert len(model.inputs) == 6

    asyncio.run(scenario())


def test_music_filters_input_from_actual_simulation_state(tmp_path):
    """通过真实动作改变第二票音乐状态，再观察语音输入过滤和停止。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(tmp_path)
        (await voice.submit_transcript("小莫小莫"))
        model.actions = [
            {"name": "play_music", "arguments": {"song_name": "夜曲"}}
        ]
        assert (
            await voice.submit_transcript("播放音乐")
        ).status == "completed"
        assert (
            await voice.submit_transcript("今天的天气")
        ).status == "filtered"
        model.actions = [{"name": "stop_music", "arguments": {}}]
        assert (
            await voice.submit_transcript("停止音乐")
        ).status == "completed"
        assert (
            await voice.submit_transcript("今天的天气")
        ).status == "completed"
        assert model.inputs == ["播放音乐", "停止音乐", "今天的天气"]

    asyncio.run(scenario())


def test_tts_retry_degradation_and_explicit_recovery(tmp_path):
    """重试仅合成，连续失败降级；显式恢复不重复原动作。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(
            tmp_path, tts_attempts=2, failure_threshold=2
        )
        tts.failures = 1
        assert (
            await voice.submit_transcript("小沫小沫")
        ).tts_status == "completed"
        tts.failures = 10
        assert (await voice.submit_transcript("请点头")).tts_status == "failed"
        assert (
            await voice.submit_transcript("请点头")
        ).tts_status == "degraded"
        assert (
            await voice.submit_transcript("请点头")
        ).tts_status == "disabled"
        assert len(model.inputs) == 3
        assert speech.events[-1] == "resume"
        voice.enable_tts()
        tts.failures = 0
        assert (
            await voice.submit_transcript("请点头")
        ).tts_status == "completed"
        (await voice.aclose())
        assert voice.state == "closed"
        assert (await voice.submit_transcript("请点头")).status == "rejected"

    asyncio.run(scenario())


def test_collecting_pauses_before_model_and_resumes_after_failure(tmp_path):
    """整个模型/动作/合成阶段暂停采集，合成异常仍能处理下一轮。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(tmp_path)
        original = model.complete

        async def complete(text, deadline, *, tools=None):
            """从 provider Adapter 观察半双工交接时序。"""
            assert speech.events[-1] == "pause"
            return await original(text, deadline, tools=tools)

        model.complete = complete
        assert (
            await voice.submit_recording(tmp_path / "input.wav")
        ).status == "completed"
        assert speech.events[-1] == "resume"

    asyncio.run(scenario())


@pytest.mark.parametrize("failed_operation", ["write_text", "replace"])
def test_asr_and_storage_failure_release_turn(
    tmp_path, monkeypatch, failed_operation
):
    """识别失败不执行动作，记录写入异常也不会永久忙碌。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(tmp_path)
        original = speech.recognize

        def fail(path, timeout):
            """模拟一次在线识别失败。"""
            raise OSError("offline")

        speech.recognize = fail
        assert (
            await voice.submit_recording(tmp_path / "input.wav")
        ).asr_status == "failed"
        assert model.inputs == []
        speech.recognize = original
        original_operation = getattr(type(tmp_path), failed_operation)

        def fail_write(path, *args, **kwargs):
            """模拟外部磁盘失败，回执仍保留已确认的执行事实。"""
            raise OSError("disk unavailable")

        monkeypatch.setattr(type(tmp_path), failed_operation, fail_write)
        result = await voice.submit_recording(tmp_path / "input.wav")
        assert result.record_status == "failed"
        assert result.actions[0].status == "simulated_success"
        assert result.tts_status == "completed"
        assert result.audio_path.endswith(result.turn_id + ".wav")
        assert voice.state == "standby"
        assert speech.events[-1] == "resume"
        monkeypatch.setattr(
            type(tmp_path), failed_operation, original_operation
        )
        assert (
            await voice.submit_recording(tmp_path / "input.wav")
        ).status == "completed"

    asyncio.run(scenario())


def test_close_releases_adapters_during_provider_call(tmp_path):
    """退出时关闭在途语音资源，不恢复已关闭的采集连接。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        original = model.complete

        async def complete(text, deadline, *, tools=None):
            """本地模型 I/O 可取消，连接资源由关闭流程接管。"""
            entered.set()
            await release.wait()
            return await original(text, deadline, tools=tools)

        model.complete = complete
        turn = asyncio.create_task(
            voice.submit_recording(tmp_path / "input.wav")
        )
        await entered.wait()
        assert voice.state == "processing"
        await voice.aclose()
        with pytest.raises(asyncio.CancelledError):
            await turn
        assert speech.events[-1] == "close"
        assert voice.state == "closed"

    asyncio.run(scenario())


@pytest.mark.parametrize("save_failed", [False, True])
def test_unknown_action_can_be_reconciled_without_reexecution(
    tmp_path, monkeypatch, save_failed
):
    """语音入口保留既有迟到回执核对 Interface，不重发动作。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        speech, model, tts = FixedSpeech(), FixedModel(), FixedTTS()
        actions = create_default_actions().registry
        release = asyncio.Event()
        finished = asyncio.Event()
        executions = []

        async def nod(**parameters):
            """模拟迟到的确认回执，通过公开动作 Seam 控制设备结果。"""
            executions.append("nod")
            await release.wait()
            finished.set()
            return {"status": "simulated_success", "detail": "迟到确认"}

        actions.register_many({"head_nod": ActionHandler(nod)})
        voice = AgentApplication(
            Agent(model, actions, action_timeout=0.01),
            speech,
            tts,
            tmp_path,
            music_playing=lambda: False,
            recognize_recording=speech.recognize,
        )
        model.actions = [
            {"name": "head_nod", "arguments": {}},
            {"name": "head_nod", "arguments": {}},
        ]

        def failed_replace(path, destination):
            """初次记录不可保存时，核对仍须记住原识别文本。"""
            raise OSError("disk unavailable")

        with monkeypatch.context() as storage:
            if save_failed:
                storage.setattr(Path, "replace", failed_replace)
            result = await voice.submit_recording(tmp_path / "input.wav")
        assert result.record_status == (
            "failed" if save_failed else "completed"
        )
        snapshot = result_to_json(result)
        assert result.actions[0].status == "unknown"
        release.set()
        assert await finished.wait()
        # 设备函数返回后 Future 才提交回执；公共核对可暂时返回仍未知。
        deadline = time.monotonic() + 1
        while True:
            reconciled = await voice.reconcile(result.turn_id)
            if reconciled.actions[0].status == "simulated_success":
                break
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
        assert reconciled.transcript == "请点头"
        assert reconciled.tts_status == "completed"
        assert executions == ["nod"]
        assert reconciled.actions[1].status == "not_executed"
        assert result_to_json(result) == snapshot
        assert model.inputs == ["请点头"]
        assert reconciled.audio_path.endswith(result.turn_id + ".wav")
        saved = json.loads((tmp_path / (result.turn_id + ".json")).read_text())
        assert saved == result_to_json(reconciled)
        model.actions = [{"name": "head_nod", "arguments": {}}]
        assert (
            await voice.submit_recording(tmp_path / "input.wav")
        ).status == "completed"

    asyncio.run(scenario())


def test_filtered_input_does_not_extend_silence_and_playback_failure_recovers(
    tmp_path,
):
    """过滤不会无限维持唤醒；播放失败保留回复音频并释放回合。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        now = [0.0]

        def fail_playback(path):
            """模拟缺失播放设备。"""
            raise RuntimeError("device absent")

        voice, speech, model, tts = make_voice(
            tmp_path, clock=lambda: now[0], playback=fail_playback
        )
        (await voice.submit_transcript("小沫小沫"))
        model.actions = [
            {"name": "play_music", "arguments": {"song_name": "夜曲"}}
        ]
        result = await voice.submit_transcript("播放音乐")
        assert result.playback_status == "failed"
        assert result.tts_status == "completed"
        now[0] = 119
        assert (await voice.submit_transcript("天气")).status == "filtered"
        now[0] = 120
        assert voice.state == "standby"

    asyncio.run(scenario())


def test_empty_microphone_recognition_does_not_extend_wake_session(tmp_path):
    """持续录音中的空识别不算用户活动，静音期限仍使会话回待机。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        now = [0.0]
        voice, speech, model, tts = make_voice(tmp_path, clock=lambda: now[0])
        (await voice.submit_transcript("小沫小沫"))
        now[0] = 60
        speech.text = ""
        result = await voice.submit_recording(
            tmp_path / "input.wav", direct=False
        )
        assert result.status == "rejected"
        now[0] = 121
        assert voice.state == "standby"
        assert model.inputs == []

    asyncio.run(scenario())


def test_unexpected_synthesis_error_surfaces_and_restores_input(tmp_path):
    """合成器编程错误向外显露，但仍恢复输入并允许下一回合。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(tmp_path)
        original = tts.synthesize

        def broken_synthesis(text, destination, timeout):
            """模拟不属于I/O失败的合成器实现错误。"""
            raise ValueError("invalid synthesis implementation")

        tts.synthesize = broken_synthesis
        with pytest.raises(
            ValueError, match="invalid synthesis implementation"
        ):
            (await voice.submit_recording(tmp_path / "input.wav"))
        assert speech.events == ["recognize", "pause", "resume"]
        assert voice.state == "standby"
        tts.synthesize = original
        assert (
            await voice.submit_transcript("请点头", direct=True)
        ).status == "completed"
        assert len(model.inputs) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("entry", ["recording", "transcript", "reconcile"])
def test_closed_voice_rejects_each_entry_without_adapter_calls(
    tmp_path, entry
):
    """所有入口关闭后直接拒绝，不调用识别、模型或合成适配器。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        voice, speech, model, tts = make_voice(tmp_path)
        (await voice.aclose())
        if entry == "recording":
            result = await voice.submit_recording(tmp_path / "input.wav")
        elif entry == "transcript":
            result = await voice.submit_transcript("请点头", direct=True)
        else:
            result = await voice.reconcile("a" * 32)
        assert result.status == "rejected"
        assert speech.events == ["close"]
        assert model.inputs == []
        assert tts.replies == []
        assert list(tmp_path.iterdir()) == []

    asyncio.run(scenario())
