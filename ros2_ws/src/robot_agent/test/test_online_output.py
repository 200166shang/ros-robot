"""语音输出Interface的总预算、播放、取消与事实保存。"""

import asyncio
import json
import time

import pytest
from async_speech_fixture import acknowledge, event, speech_server
from test_online_voice import FixedModel, FixedSpeech

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.application import AgentApplication
from robot_agent.conversation.agent import Agent
from robot_agent.results import (
    ActionOutcome,
    ExecutionResult,
    TurnResult,
    make_result,
)
from robot_agent.voice._async_speech_task import SpeechTransportError
from robot_agent.voice.output import VoiceOutput
from robot_agent.voice.speech import DashScopeTTS


def test_synthesis_retries_share_total_stage_budget(tmp_path):
    """延迟也消耗同一预算，有限重试不能各获得完整期限。"""

    class Speech:
        """只替换真实语音提供方Seam。"""

        def __init__(self):
            """记录实际尝试及剩余预算。"""
            self.timeouts = []

        async def synthesize(self, text, destination, timeout):
            """模拟临时网络故障。"""
            self.timeouts.append(timeout)
            await asyncio.sleep(0.02)
            raise SpeechTransportError("offline")

        async def aclose(self):
            """此提供方没有本地连接。"""

    async def scenario():
        """只在输出Seam验证期限，不重建回合流程。"""
        speech = Speech()
        output = VoiceOutput(speech, tmp_path, None, 0.07, 10, 2, 0.03)
        started = time.monotonic()
        record = await output.complete(
            make_result("a" * 32, "completed", "回复"), "文本", "standby"
        )
        assert record.tts_status == "failed"
        assert len(speech.timeouts) == 2
        assert 0 < speech.timeouts[1] < 0.04
        assert time.monotonic() - started < 0.15
        await output.aclose()

    asyncio.run(scenario())


def test_file_failure_is_not_retried_as_transient_synthesis(tmp_path):
    """磁盘失败不借网络重试策略反复合成，执行事实仍能保存。"""

    class Speech:
        """文件写入失败来自外部存储Seam。"""

        def __init__(self):
            """记录真实合成次数。"""
            self.attempts = 0

        async def synthesize(self, text, destination, timeout):
            """原生Adapter仅将网络错误分类为可重试。"""
            self.attempts += 1
            raise OSError("disk full")

        async def aclose(self):
            """无连接可关闭。"""

    async def scenario():
        """所有失败回合仍返回独立输出状态。"""
        speech = Speech()
        output = VoiceOutput(speech, tmp_path, None, 1, 3, 2, 0)
        record = await output.complete(
            make_result("b" * 32, "completed", "回复"), "文本", "standby"
        )
        assert speech.attempts == 1
        assert record.tts_status == "failed"
        assert record.status == "completed"
        assert record.record_status == "completed"
        await output.aclose()

    asyncio.run(scenario())


def test_cancel_retry_delay_saves_confirmed_turn_before_propagating(tmp_path):
    """关闭重试等待不能丢失此前已确认的动作事实。"""

    class Speech:
        """第一次合成失败后通知调用者。"""

        async def synthesize(self, text, destination, timeout):
            """只有临时网络错误允许进入重试延迟。"""
            raise SpeechTransportError("offline")

        async def aclose(self):
            """此提供方没有外部连接。"""

    async def scenario():
        """取消输出后仍可检查既有平铺JSON中的动作事实。"""
        turn = TurnResult.from_execution(
            ExecutionResult(
                "c" * 32,
                "completed",
                "已确认",
                (ActionOutcome("head_nod", {}, "real_success"),),
            )
        )
        output = VoiceOutput(Speech(), tmp_path, None, 10, 3, 2, 1)
        pending = asyncio.create_task(output.complete(turn, "点头", "standby"))
        await asyncio.sleep(0.02)
        await output.aclose()
        with pytest.raises(asyncio.CancelledError):
            await pending
        saved = json.loads((tmp_path / (turn.turn_id + ".json")).read_text())
        assert saved["actions"][0]["status"] == "real_success"
        assert saved["tts_status"] == "failed"

    asyncio.run(scenario())


def test_native_tts_permanent_failure_degrades_by_turn_and_recovers_explicitly(
    tmp_path, monkeypatch
):
    """永久错误不重试，降级按失败回合计数，恢复只影响新回合。"""

    async def scenario():
        """保持真实TTS传输与完整应用，不通过输出Seam重新提交动作。"""
        requests, executions = [], []
        fail = True

        async def handler(socket):
            """固定任务失败或返回完整PCM，响应不访问云端。"""
            command = await acknowledge(socket)
            requests.append(command)
            await socket.recv()
            await socket.recv()
            if fail:
                await event(socket, command, "task-failed")
            else:
                await socket.send(bytes(3200))
                await event(socket, command, "task-finished")
            await socket.wait_closed()

        async def nod():
            """动作Seam确认一次调用，检测输出失败是否重跑动作。"""
            executions.append("nod")
            return {"status": "simulated_success"}

        async with speech_server(monkeypatch, handler):
            capabilities = create_default_actions()
            capabilities.registry.register("head_nod", nod)
            model = FixedModel()
            voice = AgentApplication(
                Agent(model, capabilities.registry),
                FixedSpeech(),
                DashScopeTTS({}),
                tmp_path,
                lambda: False,
                tts_attempts=3,
                failure_threshold=2,
                retry_delay=0,
            )
            records = [
                await voice.submit_transcript("点头", direct=True)
                for _ in range(3)
            ]
            assert [record.tts_status for record in records] == [
                "failed",
                "degraded",
                "disabled",
            ]
            assert len(requests) == 2
            assert executions == ["nod"] * 3
            assert all(
                record.actions[0].status == "simulated_success"
                for record in records
            )
            voice.enable_tts()
            fail = False
            recovered = await voice.submit_transcript("再点头", direct=True)
            assert recovered.tts_status == "completed"
            assert len(requests) == 3
            assert executions == ["nod"] * 4
            assert model.inputs == ["点头"] * 3 + ["再点头"]
            await voice.aclose()

    asyncio.run(scenario())
