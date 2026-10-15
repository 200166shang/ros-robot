"""从文本交互 Interface 验证在线回合行为。"""

import asyncio
import time
from typing import Any, Dict, Optional

import pytest

import robot_agent.actions.execution as execution
from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.contracts import ActionInput, Number
from robot_agent.actions.execution import ActionExecutionError
from robot_agent.actions.registry import ActionHandler
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.memory import ConversationMemory
from robot_agent.results import ModelReply, ToolCall


class PitchInput(ActionInput):
    """外部设备的显式角度参数。"""

    pitch: Number = 90


class DisplayInput(ActionInput):
    """外部显示设备的显式参数。"""

    message: str = "默认"
    options: Optional[Dict[str, Any]] = None


class CustomLevelInput(ActionInput):
    """测试能力目录的默认值和别名。"""

    level: Number = 5


class FixedProvider:
    """替代外部模型，提供固定的完整输出或流式片段。"""

    def __init__(self, actions=(), response="你好"):
        """保存本轮模型输出。"""
        self.actions = actions
        self.response = response

    async def complete(self, text, deadline, *, tools=None):
        """返回完整的原生模型记录。"""
        return ModelReply(
            self.response,
            ToolCall(
                "fixture_call",
                "execute_actions",
                {"actions": list(self.actions)},
            )
            if self.actions
            else None,
        )

    async def aclose(self, deadline=None):
        """固定模型没有本地连接资源。"""
        pass


async def await_reconciliation(agent, turn_id, confirmed):
    """只轮询公共核对入口；限定等待，失败时直接报告未确认。"""
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        result = await agent.reconcile(turn_id)
        if confirmed(result):
            return result
        await asyncio.sleep(0.005)
    raise AssertionError("迟到设备回执未在测试期限内确认")


def test_chat_and_repeated_actions_across_turns():
    """普通聊天及跨回合重复动作均经公共入口得到可信结果。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        provider = FixedProvider()
        agent = Agent(provider, create_default_actions().registry)
        assert (await agent.submit("你好")).reply == "你好"
        provider.actions = [
            {"name": "head_nod", "arguments": {}},
            {"name": "head_smile", "arguments": {}},
            {"name": "head_nod", "arguments": {}},
        ]
        first = await agent.submit("点头微笑点头")
        second = await agent.submit("再做一次")
        assert [a.name for a in first.actions] == [
            "head_nod",
            "head_smile",
            "head_nod",
        ]
        assert [a.status for a in second.actions] == ["simulated_success"] * 3
        assert first.turn_id != second.turn_id
        assert "模拟" in first.reply

    asyncio.run(scenario())


def test_invalid_list_executes_nothing():
    """后项无效时首项也不能执行。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        events = []

        def execute():
            """代表外部设备记录实际发出的调用。"""
            events.append("sent")
            return {"status": "real_success"}

        registry = create_default_actions().registry
        registry.register("device", execute)
        for invalid in (
            "unknown",
            "head_nod(1)",
            "head_nod(x=1)",
            "head_nod(__import__('os'))",
        ):
            agent = Agent(
                FixedProvider([{"name": "device", "arguments": {}}, invalid]),
                registry,
            )
            assert (await agent.submit("执行")).status == "rejected"
        assert events == []

    asyncio.run(scenario())


def test_failure_stops_and_reports_remaining():
    """失败回执保留前项成功与后项未执行。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        registry = create_default_actions().registry

        def fail():
            """返回外部设备的失败回执。"""
            return {"status": "failed"}

        registry.register("failure", fail)
        agent = Agent(
            FixedProvider(
                [
                    {"name": "head_nod", "arguments": {}},
                    {"name": "failure", "arguments": {}},
                    {"name": "head_smile", "arguments": {}},
                ],
                "已经全成功",
            ),
            registry,
        )
        result = await agent.submit("执行")
        assert [a.status for a in result.actions] == [
            "simulated_success",
            "failed",
            "not_executed",
        ]
        assert "已经全成功" not in result.reply

    asyncio.run(scenario())


def test_complete_model_reply_executes_plan_once():
    """完整模型记录保留计划中的重复动作。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        class StreamProvider:
            """代表增量在线模型输出。"""

            async def complete(self, text, deadline, *, tools=None):
                """按字符提供 JSON 片段。"""
                return ModelReply(
                    "已完成",
                    ToolCall(
                        "fixture_call",
                        "execute_actions",
                        {
                            "actions": [{"name": "head_nod", "arguments": {}}]
                            * 2
                        },
                    ),
                )

            async def aclose(self, deadline=None):
                """固定模型没有本地连接资源。"""
                pass

        result = await Agent(
            StreamProvider(), create_default_actions().registry
        ).submit("执行")
        assert len(result.actions) == 2
        assert result.status == "completed"

    asyncio.run(scenario())


def test_action_timeout_is_unknown_and_busy_until_return():
    """在途超时保持未知且阻止新回合，不重试动作。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        released = asyncio.Event()
        sent = asyncio.Event()

        async def slow():
            """模拟已发出且尚未确认的外部调用。"""
            sent.set()
            await released.wait()
            return {"status": "real_success"}

        registry = create_default_actions().registry
        registry.register("slow", slow)
        agent = Agent(
            FixedProvider(
                [
                    {"name": "slow", "arguments": {}},
                    {"name": "head_nod", "arguments": {}},
                ]
            ),
            registry,
            action_timeout=0.02,
        )
        try:
            result = await agent.submit("执行")
            assert sent.is_set()
            assert [a.status for a in result.actions] == [
                "unknown",
                "not_executed",
            ]
            assert (await agent.submit("再次执行")).status == "busy"
        finally:
            released.set()

    asyncio.run(scenario())


def test_provider_timeout_blocks_next_turn_until_call_finishes():
    """等待已超时的调用结束，不把等待超时当作调用完成或重试动作。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        released = asyncio.Event()

        class SlowProvider:
            """代表超出主链等待期限的模型连接。"""

            async def complete(self, text, deadline, *, tools=None):
                """外部释放前保持真实调用在途。"""
                await released.wait()
                return ModelReply(
                    "好了",
                    ToolCall(
                        "fixture_call",
                        "execute_actions",
                        {"actions": [{"name": "head_nod", "arguments": {}}]},
                    ),
                )

            async def aclose(self, deadline=None):
                """固定模型没有本地连接资源。"""
                pass

        agent = Agent(
            SlowProvider(),
            create_default_actions().registry,
            provider_timeout=0.01,
        )
        try:
            first = await agent.submit("你好")
            assert first.status == "failed"
            assert first.actions == ()
            assert (await agent.submit("下一轮")).status == "busy"
        finally:
            released.set()

    asyncio.run(scenario())


def test_exception_and_invalid_receipt_cannot_be_success():
    """设备编程错误继续抛出，结果快照保留未知和余项。"""
    registry = create_default_actions().registry

    def error():
        """代表已提交设备之后出现的实现错误。"""
        raise RuntimeError("internal secret")

    registry.register("error", error)
    agent = Agent(
        FixedProvider(
            [
                {"name": "error", "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ]
        ),
        registry,
    )
    with pytest.raises(ActionExecutionError) as failure:
        asyncio.run(agent.submit("执行"))
    assert isinstance(failure.value.__cause__, RuntimeError)
    assert [a.status for a in agent.last_result.actions] == [
        "unknown",
        "not_executed",
    ]


def test_parameter_validation_precedes_all_execution():
    """设备参数校验失败整表拒绝；有效字面量参数保持原序。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        events = []

        def position(pitch=0):
            """记录设备 Adapter 的公开输入并返回确认。"""
            events.append(pitch)
            return {"status": "real_success", "detail": "已确认"}

        def validate(pitch=0):
            """拒绝超出源头部角度范围的参数。"""
            if type(pitch) not in (int, float) or not 65 <= pitch <= 120:
                raise ValueError("pitch 越界")

        registry = create_default_actions().registry
        registry.register("head_position", position, validate, PitchInput)
        provider = FixedProvider(
            [
                {"name": "head_position", "arguments": {"pitch": 70}},
                {"name": "head_position", "arguments": {"pitch": 200}},
            ]
        )
        agent = Agent(provider, registry)
        assert (await agent.submit("执行")).status == "rejected"
        assert events == []
        provider.actions = [
            {"name": "head_position", "arguments": {"pitch": 70}},
            {"name": "head_position", "arguments": {"pitch": 80}},
        ]
        result = await agent.submit("执行")
        assert events == [70, 80]
        assert [a.parameters for a in result.actions] == [
            {"pitch": 70},
            {"pitch": 80},
        ]
        assert [a.status for a in result.actions] == [
            "real_success",
            "real_success",
        ]

    asyncio.run(scenario())


def test_standalone_protocol_mismatch_and_unconfirmed_receipt_rejected():
    """旧协议对象不能进入动作绑定，无效设备回执报告未知。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        class DuplicateProvider:
            """提供有歧义的外部输出。"""

            async def complete(self, text, deadline, *, tools=None):
                """返回重复字段。"""
                return (
                    '{"function":[],"function":["head_nod"],"response":"好了"}'
                )

            async def aclose(self, deadline=None):
                """固定模型没有本地连接资源。"""
                pass

        with pytest.raises(AttributeError, match="tool_call"):
            await Agent(
                DuplicateProvider(), create_default_actions().registry
            ).submit("执行")
        registry = create_default_actions().registry

        def invalid():
            """模拟不符合设备回执契约的响应。"""
            return "设备调用失败"

        registry.register("invalid", invalid)
        result = await Agent(
            FixedProvider(
                [
                    {"name": "invalid", "arguments": {}},
                    {"name": "head_nod", "arguments": {}},
                ]
            ),
            registry,
        ).submit("执行")
        assert [a.status for a in result.actions] == [
            "unknown",
            "not_executed",
        ]

    asyncio.run(scenario())


def test_native_parameter_defaults_and_nested_values():
    """原生对象参数应用默认值并保留嵌套输入快照。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        registry = create_default_actions().registry

        def display(message="默认", options=None):
            """设备回执携带收到的业务参数，供交互结果观察。"""
            return {"status": "simulated_success", "detail": message}

        registry.register("display", display, inputs=DisplayInput)
        provider = FixedProvider(
            [
                {"name": "head_nod", "arguments": {}},
                {"name": "display", "arguments": {}},
                {"name": "display", "arguments": {}},
                {
                    "name": "display",
                    "arguments": {
                        "message": "你好",
                        "options": {"colors": ["red"], "enabled": True},
                    },
                },
                {
                    "name": "display",
                    "arguments": {"options": None, "message": "关键字"},
                },
            ]
        )
        result = await Agent(provider, registry).submit("按顺序显示")
        assert result.status == "completed"
        assert [action.parameters for action in result.actions] == [
            {},
            {"message": "默认", "options": None},
            {"message": "默认", "options": None},
            {
                "message": "你好",
                "options": {"colors": ("red",), "enabled": True},
            },
            {"message": "关键字", "options": None},
        ]

    asyncio.run(scenario())


def test_unsupported_call_forms_reject_the_whole_list():
    """展开参数、重复参数和属性调用均不能越过整表校验。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        registry = create_default_actions().registry
        provider = FixedProvider()
        agent = Agent(provider, registry)
        for source in (
            "head_nod(*[])",
            "head_nod(**{})",
            "head_nod(x=1, x=2)",
            "device.head_nod()",
            "head_nod(1+2)",
        ):
            provider.actions = [
                {"name": "head_smile", "arguments": {}},
                source,
            ]
            result = await agent.submit("执行")
            assert result.status == "rejected"
            assert result.actions == ()

    asyncio.run(scenario())


def test_late_action_requires_explicit_reconciliation():
    """动作线程结束后仍保持忙，只有核对迟到回执才恢复。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        release = asyncio.Event()
        returned = asyncio.Event()

        async def slow():
            """代表不可取消的设备调用。"""
            await release.wait()
            returned.set()
            return {"status": "real_success", "detail": "设备确认完成"}

        registry = create_default_actions().registry
        registry.register("slow", slow)
        provider = FixedProvider(
            [
                {"name": "head_nod", "arguments": {}},
                {"name": "slow", "arguments": {}},
                {"name": "head_smile", "arguments": {}},
            ]
        )
        agent = Agent(provider, registry, action_timeout=0.02)
        try:
            result = await agent.submit("执行")
            release.set()
            assert await returned.wait()
            assert (await agent.submit("下一轮")).status == "busy"
            reconciled = await await_reconciliation(
                agent,
                result.turn_id,
                lambda reply: reply.actions[1].status == "real_success",
            )
            assert [a.status for a in reconciled.actions] == [
                "simulated_success",
                "real_success",
                "not_executed",
            ]
            provider.actions = []
            assert (await agent.submit("你好")).status == "completed"
            assert result.actions[1].status == "unknown"
        finally:
            release.set()

    asyncio.run(scenario())


def test_reporting_failure_preserves_completed_action(monkeypatch):
    """回复格式异常继续抛出，同时携带已经确认的设备事实。"""

    def broken_reply(actions):
        """注入已有报告故障契约。"""
        raise ValueError("private error")

    monkeypatch.setattr(execution, "confirmed_action_reply", broken_reply)
    agent = Agent(
        FixedProvider([{"name": "head_nod", "arguments": {}}]),
        create_default_actions().registry,
    )
    with pytest.raises(ActionExecutionError) as failure:
        asyncio.run(agent.submit("执行"))
    assert isinstance(failure.value.__cause__, ValueError)
    assert failure.value.result.actions[0].status == "simulated_success"
    assert agent.last_result.actions[0].status == "simulated_success"


def test_uncertain_late_receipt_does_not_restore_service():
    """迟到的未知或异常回执不能恢复接入，核对不重试动作。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        for raises in (False, True):
            release = asyncio.Event()
            calls = []

            async def slow():
                """模拟设备完成 I/O 后仍不能确认最终状态。"""
                calls.append("sent")
                await release.wait()
                if raises:
                    raise RuntimeError("private failure")
                return {"status": "unknown", "detail": "设备无法确认"}

            registry = create_default_actions().registry
            registry.register("slow", slow)
            agent = Agent(
                FixedProvider(
                    [
                        {"name": "slow", "arguments": {}},
                        {"name": "head_nod", "arguments": {}},
                    ]
                ),
                registry,
                action_timeout=0.02,
            )
            try:
                result = await agent.submit("执行")
                assert (await agent.reconcile("wrong-id")).status == "rejected"
                release.set()
                if raises:
                    await asyncio.sleep(0)
                    with pytest.raises(ActionExecutionError):
                        await agent.reconcile(result.turn_id)
                else:
                    reconciled = await await_reconciliation(
                        agent,
                        result.turn_id,
                        lambda reply: "最终状态仍未知" in reply.reply,
                    )
                    assert [a.status for a in reconciled.actions] == [
                        "unknown",
                        "not_executed",
                    ]
                assert (await agent.submit("下一轮")).status == "busy"
                assert calls == ["sent"]
            finally:
                release.set()

    asyncio.run(scenario())


def test_late_failure_reconciles_without_executing_remaining_actions():
    """设备明确失败也能解除不确定状态，后续动作不补执行。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        release = asyncio.Event()

        async def slow_failure():
            """提供迟到的明确失败回执。"""
            await release.wait()
            return {"status": "failed", "detail": "设备确认失败"}

        registry = create_default_actions().registry
        registry.register("slow_failure", slow_failure)
        provider = FixedProvider(
            [
                {"name": "slow_failure", "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ]
        )
        agent = Agent(provider, registry, action_timeout=0.02)
        try:
            result = await agent.submit("执行")
            release.set()
            reconciled = await await_reconciliation(
                agent,
                result.turn_id,
                lambda reply: reply.actions[0].status == "failed",
            )
            assert [a.status for a in reconciled.actions] == [
                "failed",
                "not_executed",
            ]
            provider.actions = []
            assert (await agent.submit("聊天")).status == "completed"
        finally:
            release.set()

    asyncio.run(scenario())


def test_validation_exception_reports_its_stage_and_executes_nothing():
    """校验器编程错误不转成普通失败，且整表没有提交设备。"""
    calls = []

    def execute():
        """外部设备出口记录实际动作。"""
        calls.append("sent")
        return {"status": "real_success"}

    def validate():
        """代表实现错误，不属于业务参数拒绝。"""
        raise RuntimeError("private validation failure")

    registry = create_default_actions().registry
    registry.register("device", execute, validate)
    agent = Agent(
        FixedProvider(
            [
                {"name": "head_nod", "arguments": {}},
                {"name": "device", "arguments": {}},
            ]
        ),
        registry,
    )
    with pytest.raises(RuntimeError, match="private validation failure"):
        asyncio.run(agent.submit("执行"))
    assert calls == []


def test_late_model_output_is_discarded_without_executing_actions():
    """模型超时后迟到的动作建议被丢弃，调用结束后可接入新聊天。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""

        release = asyncio.Event()
        submitted = []

        class SlowFirstProvider:
            """第一次响应延迟，后续请求正常返回聊天。"""

            def __init__(self):
                """保存外部请求次数。"""
                self.calls = 0

            async def complete(self, text, deadline, *, tools=None):
                """第一次返回迟到动作列表，后续返回普通聊天。"""
                self.calls += 1
                if self.calls == 1:
                    await release.wait()
                    return ModelReply(
                        "动作建议",
                        ToolCall(
                            "fixture_call",
                            "execute_actions",
                            {"actions": [{"name": "device", "arguments": {}}]},
                        ),
                    )
                return ModelReply("新的聊天")

            async def aclose(self, deadline=None):
                """固定模型没有本地连接资源。"""
                pass

        def execute():
            """记录设备调用，迟到模型输出不得触发它。"""
            submitted.append("sent")
            return {"status": "real_success"}

        registry = create_default_actions().registry
        registry.register("device", execute)
        agent = Agent(SlowFirstProvider(), registry, provider_timeout=0.02)
        try:
            first = await agent.submit("请求动作")
            assert first.status == "failed" and not first.actions
            release.set()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                next_turn = await agent.submit("聊天")
                if next_turn.status != "busy":
                    break
                await asyncio.sleep(0.005)
            assert next_turn.reply == "新的聊天"
            assert not next_turn.actions
            assert submitted == []
        finally:
            release.set()

    asyncio.run(scenario())


def test_bulk_capability_loading_preserves_validation_and_replacement():
    """批量能力表复用整表校验，并允许配置阶段替换已有动作。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        calls = []

        def execute(level=5):
            """记录由能力表绑定的业务参数。"""
            calls.append(level)
            return {"status": "simulated_success", "detail": str(level)}

        def validate(level=5):
            """拒绝无效业务输入，不能修改执行记录。"""
            if level < 0:
                raise ValueError("level 必须非负")

        handler = ActionHandler(execute, validate, CustomLevelInput)
        registry = create_default_actions().registry
        registry.register_many({"custom": handler, "alias": handler})
        registry.register_many({"head_smile": handler})
        provider = FixedProvider(
            [
                {"name": "custom", "arguments": {"level": 2}},
                {"name": "alias", "arguments": {"level": -1}},
            ]
        )
        agent = Agent(provider, registry)
        assert (await agent.submit("执行")).status == "rejected"
        assert calls == []
        provider.actions = [
            {"name": "custom", "arguments": {"level": 2}},
            {"name": "alias", "arguments": {"level": 3}},
            {"name": "head_smile", "arguments": {}},
        ]
        assert (await agent.submit("执行")).status == "completed"
        assert calls == [2, 3, 5]

    asyncio.run(scenario())


def test_caller_cancellation_retains_original_action_and_skips_memory(
    tmp_path,
):
    """取消回合等待不能取消设备或丢失已提交事实，核对不补执行。"""

    async def scenario():
        """通过公共提交和核对观察取消后的设备归属。"""
        entered, release = asyncio.Event(), asyncio.Event()
        sent = []

        async def action():
            """已发出的操作在原 Task 内等待设备确认。"""
            sent.append("sent")
            entered.set()
            await release.wait()
            return {"status": "real_success", "data": {"enabled": True}}

        registry = create_default_actions().registry
        registry.register("action", action)
        memory = ConversationMemory(tmp_path / "memory.json")
        agent = Agent(
            FixedProvider(
                [
                    {"name": "action", "arguments": {}},
                    {"name": "head_nod", "arguments": {}},
                ]
            ),
            registry,
            memory=memory,
        )
        turn = asyncio.create_task(agent.submit("failed-turn-marker"))
        await entered.wait()
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        result = agent.last_result
        assert [a.status for a in result.actions] == [
            "unknown",
            "not_executed",
        ]
        assert "failed-turn-marker" not in memory.context("next")
        assert (await agent.submit("下一轮")).status == "busy"
        release.set()
        reconciled = await await_reconciliation(
            agent,
            result.turn_id,
            lambda reply: reply.actions[0].status == "real_success",
        )
        assert reconciled.actions[0].data == {"enabled": True}
        assert reconciled.actions[1].status == "not_executed"
        assert result.actions[0].status == "unknown"
        assert sent == ["sent"]

    asyncio.run(scenario())


def test_reconciled_turn_cannot_clear_later_pending_turn():
    """多轮核对各自归属原回合，旧标识不能解除新回合的未知状态。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        release = asyncio.Event()
        calls = []

        async def slow():
            """每轮等待明确释放后返回设备确认。"""
            calls.append("sent")
            await release.wait()
            return {"status": "real_success"}

        registry = create_default_actions().registry
        registry.register("slow", slow)
        agent = Agent(
            FixedProvider(
                [
                    {"name": "slow", "arguments": {}},
                    {"name": "head_nod", "arguments": {}},
                ]
            ),
            registry,
            action_timeout=0.02,
        )
        try:
            first = await agent.submit("第一轮")
            release.set()
            await await_reconciliation(
                agent,
                first.turn_id,
                lambda reply: reply.actions[0].status == "real_success",
            )
            release.clear()
            second = await agent.submit("第二轮")
            assert (await agent.reconcile(first.turn_id)).status == "rejected"
            assert (await agent.submit("第三轮")).status == "busy"
            release.set()
            reconciled = await await_reconciliation(
                agent,
                second.turn_id,
                lambda reply: reply.actions[0].status == "real_success",
            )
            assert reconciled.actions[1].status == "not_executed"
            assert second.actions[0].status == "unknown"
            assert calls == ["sent", "sent"]
        finally:
            release.set()

    asyncio.run(scenario())


def test_close_keeps_latest_chat_result_after_an_earlier_action():
    """没有在途动作时，关闭不能用旧执行快照覆盖最后一轮聊天事实。"""

    async def run():
        """动作、聊天和关闭使用同一 Agent 生命周期。"""
        provider = FixedProvider([{"name": "head_nod", "arguments": {}}])
        registry = create_default_actions().registry
        agent = Agent(provider, registry)
        first = await agent.submit("点头")
        provider.actions = []
        latest = await agent.submit("聊天")
        assert first.turn_id != latest.turn_id
        await agent.aclose()
        assert agent.last_result.turn_id == latest.turn_id

    asyncio.run(run())
