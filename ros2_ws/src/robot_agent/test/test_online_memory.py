"""通过交互输入验证近期上下文、摘要重启和清空。"""

import asyncio
import time

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.memory import ConversationMemory
from robot_agent.conversation.provider import ModelTransportError
from robot_agent.results import ModelReply, ToolCall


class MemoryProvider:
    """固定在线 Adapter，以收到的上下文决定可观察回复。"""

    def __init__(self):
        """记录外部请求，提供可复现摘要。"""
        self.inputs = []

    async def complete(self, text, deadline, *, tools=None):
        """按真实 JSON 契约回答或摘要，不执行动作。"""
        self.inputs.append(text)
        response = "记住了"
        if "【摘要任务】" in text:
            response = "用户喜欢蓝色。"
        elif "用户喜欢蓝色。" in text or "我喜欢蓝色" in text:
            response = "蓝色"
        return ModelReply(
            response,
            None,
        )

    async def aclose(self):
        """固定模型没有本地连接资源。"""
        pass


def test_context_summary_restart_and_clear(tmp_path):
    """跨回合使用上下文，重启恢复摘要，清空覆盖两种记忆。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        path = tmp_path / "memory.json"
        provider = MemoryProvider()
        agent = Agent(
            provider,
            create_default_actions().registry,
            memory=ConversationMemory(path, recent_turns=2, summary_trigger=2),
        )
        assert (await agent.submit("我喜欢蓝色")).status == "completed"
        assert (await agent.submit("我喜欢什么颜色？")).reply == "蓝色"
        restarted = Agent(
            provider,
            create_default_actions().registry,
            memory=ConversationMemory(path),
        )
        assert (await restarted.submit("我喜欢什么颜色？")).reply == "蓝色"
        assert (await restarted.clear_memory()).status == "completed"
        assert (await restarted.submit("我喜欢什么颜色？")).reply == "记住了"
        again = Agent(
            provider,
            create_default_actions().registry,
            memory=ConversationMemory(path),
        )
        assert (await again.submit("我喜欢什么颜色？")).reply == "记住了"

    asyncio.run(scenario())


def test_summary_failure_keeps_context_bounded(tmp_path):
    """摘要失败不阻断回复，有限近期上下文不累积过期输入。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        class FailingProvider(MemoryProvider):
            """代表摘要请求失败的外部在线模型。"""

            async def complete(self, text, deadline, *, tools=None):
                """正常对话可用，摘要发生明确外部故障。"""
                if "【摘要任务】" in text:
                    raise ModelTransportError("network", transient=True)
                return await super().complete(text, deadline, tools=tools)

            async def aclose(self):
                """固定模型没有本地连接资源。"""
                pass

        provider = FailingProvider()
        agent = Agent(
            provider,
            create_default_actions().registry,
            memory=ConversationMemory(tmp_path / "memory", 2, 2),
        )
        (await agent.submit("old-marker"))
        result = await agent.submit("second-marker")
        assert result.status == "completed"
        assert result.memory_warnings == ("summary_failed",)
        (await agent.submit("third-marker"))
        (await agent.submit("fourth-marker"))
        assert "old-marker" not in provider.inputs[-1]
        assert "second-marker" in provider.inputs[-1]
        assert "third-marker" in provider.inputs[-1]

    asyncio.run(scenario())


def test_save_failure_and_clear_failure_are_observable(tmp_path):
    """磁盘路径故障不丢失回复和内存摘要，清空失败不伪报持久成功。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        parent = tmp_path / "blocked"
        parent.write_text("not a directory", encoding="utf-8")
        agent = Agent(
            MemoryProvider(),
            create_default_actions().registry,
            memory=ConversationMemory(parent / "memory", 1, 1),
        )
        result = await agent.submit("我喜欢蓝色")
        assert result.status == "completed"
        assert result.memory_warnings == ("load_failed", "save_failed")
        assert (await agent.submit("我喜欢什么颜色？")).reply == "蓝色"
        cleared = await agent.clear_memory()
        assert cleared.status == "failed"
        assert cleared.memory_warnings == ("clear_save_failed",)
        assert (await agent.submit("我喜欢什么颜色？")).reply == "记住了"

    asyncio.run(scenario())


def test_clear_also_removes_recent_context(tmp_path):
    """尚未生成摘要时，clear 同样移除近期输入。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        provider = MemoryProvider()
        agent = Agent(
            provider,
            create_default_actions().registry,
            memory=ConversationMemory(tmp_path / "memory"),
        )
        (await agent.submit("我喜欢蓝色"))
        assert (await agent.submit("我喜欢什么颜色？")).reply == "蓝色"
        assert (await agent.clear_memory()).status == "completed"
        assert (await agent.submit("我喜欢什么颜色？")).reply == "记住了"

    asyncio.run(scenario())


def test_summary_timeout_keeps_clear_and_new_turn_busy(tmp_path):
    """摘要在途超时保留回复，拒绝并发清空及回合直到调用结束。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        released = asyncio.Event()
        finished = asyncio.Event()

        class SlowProvider(MemoryProvider):
            """代表超过交互期限的在线摘要。"""

            async def complete(self, text, deadline, *, tools=None):
                """摘要等待外部释放，正常对话立即响应。"""
                if "【摘要任务】" in text:
                    try:
                        await released.wait()
                    except asyncio.CancelledError:
                        await released.wait()
                    finished.set()
                return await super().complete(text, deadline, tools=tools)

            async def aclose(self):
                """固定模型没有本地连接资源。"""
                pass

        agent = Agent(
            SlowProvider(),
            create_default_actions().registry,
            provider_timeout=0.05,
            memory=ConversationMemory(tmp_path / "memory", 1, 1),
        )
        try:
            result = await agent.submit("我喜欢蓝色")
            assert result.status == "completed"
            assert result.memory_warnings == ("summary_timeout",)
            assert (await agent.clear_memory()).status == "busy"
            assert (await agent.submit("下一轮")).status == "busy"
        finally:
            released.set()
        assert await finished.wait()
        # 使用公开入口等待保存结束，而非依赖线程退出时刻。
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            result = await agent.clear_memory()
            if result.status != "busy":
                break
            await asyncio.sleep(0.005)
        assert result.status == "completed"

    asyncio.run(scenario())


def test_invalid_memory_file_is_reported_without_content(tmp_path):
    """损坏的外部文件不阻断启动，反馈不会泄露文件内容。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        path = tmp_path / "memory"
        path.write_text("private-invalid-data", encoding="utf-8")
        agent = Agent(
            MemoryProvider(),
            create_default_actions().registry,
            memory=ConversationMemory(path),
        )
        result = await agent.submit("你好")
        assert result.status == "completed"
        assert result.memory_warnings == ("load_failed",)
        assert "private-invalid-data" not in str(result)

    asyncio.run(scenario())


def test_summary_actions_are_rejected_without_execution(tmp_path):
    """摘要输出中的动作不会执行，当前聊天与后续上下文仍可用。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        class ActionSummaryProvider(MemoryProvider):
            """代表摘要包含动作的无效在线回复。"""

            async def complete(self, text, deadline, *, tools=None):
                """摘要提出动作，普通请求仍按固定聊天回复。"""
                if "【摘要任务】" in text:
                    return ModelReply(
                        "错误摘要",
                        ToolCall(
                            "fixture_call",
                            "execute_actions",
                            {
                                "actions": [
                                    {"name": "head_nod", "arguments": {}}
                                ]
                            },
                        ),
                    )
                return await super().complete(text, deadline, tools=tools)

            async def aclose(self):
                """固定模型没有本地连接资源。"""
                pass

        events = []

        def nod():
            """在外部设备出口记录实际调用。"""
            events.append("nod")
            return {"status": "simulated_success"}

        registry = create_default_actions().registry
        registry.register("head_nod", nod)
        agent = Agent(
            ActionSummaryProvider(),
            registry,
            memory=ConversationMemory(tmp_path / "memory", 1, 1),
        )
        result = await agent.submit("我喜欢蓝色")
        assert result.status == "completed"
        assert result.memory_warnings == ("summary_failed",)
        assert not events
        assert (await agent.submit("我喜欢什么颜色？")).reply == "蓝色"

    asyncio.run(scenario())
