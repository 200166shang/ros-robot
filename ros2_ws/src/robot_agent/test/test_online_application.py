"""应用公开异步入口的回合接纳与生命周期。"""

import asyncio
import threading

from test_online_voice import FixedModel, FixedSpeech, FixedTTS, make_voice

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.application import AgentApplication
from robot_agent.conversation.agent import Agent


def test_application_has_async_turn_entry_and_rejects_after_close(tmp_path):
    """同一应用负责回合输出，关闭后不再调用设备。"""

    async def scenario():
        """从调用者的事件循环完成一次唤醒和关闭。"""
        application, speech, model, tts = make_voice(tmp_path)
        assert isinstance(application, AgentApplication)
        assert (
            await application.submit_transcript("小莫小莫")
        ).status == "woken"
        await application.aclose()
        assert (
            await application.submit_transcript("点头")
        ).status == "rejected"
        assert speech.events == ["pause", "resume", "close"]
        assert not model.inputs

    asyncio.run(scenario())


def test_busy_application_keeps_session_awake_until_turn_finishes(tmp_path):
    """处理期间拒绝重叠输入，耗时处理不消耗会话静音预算。"""

    async def scenario():
        """通过可控模型等待观察应用状态与半双工恢复。"""
        now = [0.0]
        application, speech, model, tts = make_voice(
            tmp_path, clock=lambda: now[0]
        )
        await application.submit_transcript("小莫小莫")
        original = model.complete
        entered, release = threading.Event(), threading.Event()

        def complete(text, timeout):
            """模拟在途模型请求。"""
            entered.set()
            release.wait(2)
            return original(text, timeout)

        model.complete = complete
        turn = asyncio.create_task(application.submit_transcript("请点头"))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        now[0] = 200
        application.tick()
        assert application.state == "processing"
        assert (await application.submit_transcript("再点头")).status == "busy"
        release.set()
        assert (await turn).status == "completed"
        assert application.state == "listening"
        assert model.inputs == ["请点头"]
        await application.aclose()

    asyncio.run(scenario())


def test_agent_rejects_overlap_while_actions_are_waiting():
    """模型结束但动作仍在途时也只能有一个文本回合。"""

    async def scenario():
        """设备 Seam 保持动作在途，另一个提交应直接报告忙碌。"""
        entered, release = threading.Event(), threading.Event()
        capabilities = create_default_actions()

        def nod():
            """提供可控设备确认。"""
            entered.set()
            release.wait(2)
            return {"status": "real_success"}

        capabilities.registry.register("head_nod", nod)
        agent = Agent(FixedModel(), capabilities.registry)
        first = asyncio.create_task(agent.submit("请点头"))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        try:
            assert (await agent.submit("再点头")).status == "busy"
        finally:
            release.set()
            await first

    asyncio.run(scenario())


def test_idle_microphone_wait_expires_session_and_reports_input_failure(
    tmp_path,
):
    """空闲监听不刷新活动；输入耗尽后报告失败并关闭应用资源。"""
    now = [0.0]

    class Microphone(FixedSpeech):
        """从输入 Seam 交付唤醒、静音和后续普通句。"""

        def __init__(self):
            """准备可控的最终文本序列。"""
            super().__init__()
            self.inputs = iter([(0, "小莫小莫"), (121, None), (122, "请点头")])

        def listen(self, timeout):
            """返回超时无文本或最终文本，耗尽时模拟连接失败。"""
            try:
                now[0], text = next(self.inputs)
            except StopIteration:
                raise OSError("fixture input exhausted")
            return text

    async def scenario():
        """真实应用循环完成会话决策和输入错误收尾。"""
        speech, model, tts = Microphone(), FixedModel(), FixedTTS()
        capabilities = create_default_actions()
        application = AgentApplication(
            Agent(model, capabilities.registry),
            speech,
            tts,
            tmp_path,
            music_playing=capabilities.music_playing,
            clock=lambda: now[0],
        )
        results = []
        await application.run(results.append)
        assert [result.status for result in results] == [
            "woken",
            "ignored",
            "failed",
        ]
        assert results[-1].asr_status == "failed"
        assert application.state == "closed"
        assert speech.events[-1] == "close"
        assert not model.inputs

    asyncio.run(scenario())


def test_concurrent_close_waits_for_the_same_resource_cleanup(tmp_path):
    """关闭中再次等待不能提前返回，输出清理完成后才结束生命周期。"""

    async def scenario():
        """可控输入关闭模拟ROS循环与退出调用同时等待关闭。"""
        application, speech, model, tts = make_voice(tmp_path)
        entered, release = threading.Event(), threading.Event()
        original = speech.close

        def close():
            """在输入资源关闭中保留一个可观察的等待窗口。"""
            entered.set()
            release.wait(2)
            original()

        speech.close = close
        first = asyncio.create_task(application.aclose())
        while not entered.is_set():
            await asyncio.sleep(0.001)
        second = asyncio.create_task(application.aclose())
        try:
            await asyncio.sleep(0)
            assert not second.done()
        finally:
            release.set()
            await first
            await second
        assert speech.events == ["close"]

    asyncio.run(scenario())
