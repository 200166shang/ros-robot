"""原生动作计划经公开 Interface 的整表契约。"""

import asyncio
import io
import json
import time
from decimal import Decimal

import httpx
import pytest
from native_protocol_fixture import install_async_transport

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.perception import (
    PerceptionActions,
    perception_actions,
)
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.provider import DashScopeProvider
from robot_agent.results import ModelReply, ToolCall


def test_registry_native_plan_defaults_aliases_and_repeats():
    """同一参数声明生成 Schema 并绑定默认值，顺序和重复不变。"""
    registry = create_default_actions().registry
    plan = registry.bind_plan(
        {
            "actions": [
                {"name": "head_breathing", "arguments": {}},
                {"name": "play_song", "arguments": {"song_name": "夜曲"}},
                {"name": "head_breathing", "arguments": {}},
            ]
        }
    )
    assert [command.name for command in plan.commands] == [
        "head_breathing",
        "play_song",
        "head_breathing",
    ]
    assert plan.commands[0].parameters == {"cycles": 5, "duration": 0.5}
    schema = registry.tool_schema
    assert schema["function"]["name"] == "execute_actions"
    assert "deadline" not in json.dumps(schema)
    branches = schema["function"]["parameters"]["properties"]["actions"][
        "items"
    ]["oneOf"]
    breathing = next(
        item
        for item in branches
        if item["properties"]["name"]["const"] == "head_breathing"
    )
    assert (
        breathing["properties"]["arguments"]["properties"]["cycles"]["default"]
        == 5
    )
    assert breathing["properties"]["arguments"]["properties"]["duration"][
        "anyOf"
    ] == [
        {"type": "integer", "exclusiveMinimum": 0},
        {"type": "number", "exclusiveMinimum": 0},
    ]


@pytest.mark.parametrize("repeat_type", [False, True])
def test_provider_assembles_fragmented_native_plan(monkeypatch, repeat_type):
    """模型 Adapter 收齐名称与参数后返回完整请求。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
    events = [
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_88",
                    "type": "function",
                    "function": {
                        "name": "execute_",
                        "arguments": '{"actions":[',
                    },
                }
            ]
        },
        {
            "tool_calls": [
                {
                    "index": 0,
                    "function": {
                        "name": "actions",
                        "arguments": '{"name":"head_nod","arguments":{}}]}',
                    },
                }
            ]
        },
    ]
    if repeat_type:
        # Qwen 后续帧重复固定类型，并用空标识表示同一调用的延续。
        events[1]["tool_calls"][0].update(id="", type="function")
    wire = b"".join(
        (
            "data: "
            + json.dumps(
                {"choices": [{"delta": event, "finish_reason": None}]}
            )
            + "\n\n"
        ).encode()
        for event in events
    )
    wire += (
        b'data: {"choices":[{"delta":{},'
        b'"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n'
    )
    requests = []

    def transport(request, timeout):
        """仅替换 HTTPS 传输，保留生产协议处理。"""
        requests.append(json.loads(request.content))
        return io.BytesIO(wire)

    install_async_transport(monkeypatch, transport)
    registry = create_default_actions().registry
    reply = asyncio.run(
        DashScopeProvider({}).complete(
            "点头",
            time.monotonic() + 1,
            tools=registry.tool_schema,
        )
    )
    assert reply.tool_call.call_id == "call_88"
    assert reply.tool_call.arguments == {
        "actions": ({"name": "head_nod", "arguments": {}},)
    }
    assert requests[0]["tools"][0] == registry.tool_schema
    assert requests[0]["parallel_tool_calls"] is False
    assert "response_format" not in requests[0]


def test_agent_native_plan_invalid_tail_sends_nothing_then_confirms_facts():
    """整表末项无效时零执行；修正后采用默认值、别名并只回复回执。"""

    events = []

    class Provider:
        """替代外部模型返回完整原生请求。"""

        async def complete(self, text, deadline, *, tools=None):
            """不把模型预先成功承诺当作设备事实。"""
            return ModelReply(
                "全部真实完成",
                ToolCall("call_plan", "execute_actions", {"actions": items}),
            )

        async def aclose(self, deadline=None):
            """固定模型没有本地连接资源。"""
            pass

    def sent():
        """外部设备记录动作是否真正发出。"""
        events.append("sent")
        return {"status": "real_success"}

    registry = create_default_actions().registry
    registry.register("device", sent)
    items = [
        {"name": "device", "arguments": {}},
        {"name": "head_breathing", "arguments": {"cycles": True}},
    ]
    agent = Agent(Provider(), registry)
    assert asyncio.run(agent.submit("执行")).status == "rejected"
    assert events == []
    items[1]["arguments"] = {}
    items += [{"name": "play_song", "arguments": {"song_name": "夜曲"}}]
    result = asyncio.run(agent.submit("执行"))
    assert result.status == "completed"
    assert events == ["sent"]
    assert result.actions[1].parameters == {"cycles": 5, "duration": 0.5}
    assert result.execution.tool_call_id == "call_plan"
    assert "全部真实完成" not in result.reply


def complete_wire(
    arguments, *, finish="tool_calls", name="execute_actions", calls=None
):
    """生成完整原生 HTTP 响应，供传输 Seam 注入。"""
    if calls is None:
        calls = [
            {
                "id": "call_full",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": arguments,
                },
            }
        ]
    return json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": "全部完成",
                        "tool_calls": calls,
                    },
                    "finish_reason": finish,
                }
            ]
        }
    ).encode()


@pytest.mark.parametrize("depth", [400, 800, 1200])
def test_deep_external_arguments_are_rejected_without_retry_or_actions(
    monkeypatch, depth
):
    """外部解码及快照递归耗尽均为协议拒绝，不启动动作或重试。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")

    async def scenario():
        """生产 Adapter 到 Agent 共用本机传输和真实动作目录。"""
        requests, submitted = [], []
        arguments = '{"actions":' + "[" * depth + "0" + "]" * depth + "}"

        def respond(request):
            """只替换外部模型响应，不经过真实端点。"""
            requests.append(request)
            return httpx.Response(200, content=complete_wire(arguments))

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        registry = create_default_actions().registry
        registry.register(
            "device",
            lambda: submitted.append(True) or {"status": "real_success"},
        )
        agent = Agent(DashScopeProvider({}, client=client), registry)
        try:
            result = await agent.submit("执行")
            assert result.status == "rejected"
            assert result.actions == ()
            assert len(requests) == 1
            assert submitted == []
        finally:
            await agent.aclose()
        assert client.is_closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "wire",
    [
        complete_wire(
            '{"actions":[{"name":"device","arguments":{}}]}', name="other"
        ),
        complete_wire(
            '{"actions":[{"name":"device","arguments":{}}]}', finish="length"
        ),
        complete_wire('{"actions":['),
        complete_wire(
            '{"actions":[],"actions":[{"name":"device","arguments":{}}]}'
        ),
        complete_wire(
            '{"actions":[{"name":"device","arguments":{}},{"name":"head_breathing","arguments":{"cycles":true}}]}'
        ),
        complete_wire(
            '{"actions":[{"name":"device","arguments":{}}],"extra":1}'
        ),
        complete_wire("[]"),
        complete_wire(
            "{}",
            calls=[
                {
                    "id": "one",
                    "type": "function",
                    "function": {"name": "execute_actions", "arguments": "{}"},
                },
                {
                    "id": "two",
                    "type": "function",
                    "function": {"name": "execute_actions", "arguments": "{}"},
                },
            ],
        ),
        (
            b'data: {"choices":[{"delta":{"tool_calls":['
            b'{"index":0,"id":"a","type":"function",'
            b'"function":{"name":"execute_actions","arguments":"{}"}},'
            b'{"index":1,"id":"b","type":"function",'
            b'"function":{"name":"execute_actions","arguments":"{}"}}]},'
            b'"finish_reason":null}]}\n\n'
        ),
        (
            b'data: {"choices":[{"delta":{"content":"truncated"},'
            b'"finish_reason":null}]}\n\n'
        ),
        b"data: [DONE]\n\n",
        b'{"choices":[{"message":null,"finish_reason":"stop"}]}',
        b'data: {"choices":[{"delta":null}]}\n\n',
    ],
)
def test_real_adapter_rejects_invalid_protocol_before_any_action(
    monkeypatch, wire
):
    """完整、交错、多调用和截断的实际协议错误均不能发出首项动作。"""

    sent = []
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
    install_async_transport(
        monkeypatch, lambda request, timeout: io.BytesIO(wire)
    )
    registry = create_default_actions().registry
    registry.register(
        "device", lambda: sent.append("sent") or {"status": "real_success"}
    )
    result = asyncio.run(Agent(DashScopeProvider({}), registry).submit("执行"))
    assert result.status == "rejected"
    assert result.actions == ()
    assert sent == []


def test_full_native_response_executes_once_and_preserves_correlation(
    monkeypatch,
):
    """完整 HTTP 工具响应与 SSE 相同，动作结果保留调用标识。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
    wire = complete_wire(
        json.dumps(
            {
                "actions": [
                    {"name": "head_breathing", "arguments": {}},
                    {"name": "head_breathing", "arguments": {}},
                ]
            }
        )
    )
    install_async_transport(
        monkeypatch, lambda request, timeout: io.BytesIO(wire)
    )
    result = asyncio.run(
        Agent(DashScopeProvider({}), create_default_actions().registry).submit(
            "执行"
        )
    )
    assert result.status == "completed"
    assert [action.name for action in result.actions] == [
        "head_breathing",
        "head_breathing",
    ]
    assert result.execution.tool_call_id == "call_full"
    assert "全部完成" not in result.reply


@pytest.mark.parametrize(
    "arguments",
    [
        {"cycles": True},
        {"cycles": 1.0},
        {"cycles": "2"},
        {"cycles": 0},
        {"cycles": 65},
        {"duration": False},
        {"duration": "0.5"},
        {"duration": Decimal("0.5")},
        {"duration": 0},
        {"duration": float("inf")},
        {"duration": float("nan")},
        {"deadline": 100},
        {"extra": 1},
    ],
)
def test_registry_strict_numeric_and_extra_fields(arguments):
    """参数模型拒绝类型转换、非有限数、越界和内部参数注入。"""
    registry = create_default_actions().registry
    with pytest.raises(ValueError):
        registry.bind_plan(
            {"actions": [{"name": "head_breathing", "arguments": arguments}]}
        )


def test_registry_plan_limit_and_integer_duration():
    """64项限额接受边界，有限整数秒仍是合法数值。"""
    registry = create_default_actions().registry
    action = {"name": "head_breathing", "arguments": {"duration": 2}}
    plan = registry.bind_plan({"actions": [action] * 64})
    assert len(plan.commands) == 64
    assert type(plan.commands[0].parameters["duration"]) is int
    with pytest.raises(ValueError):
        registry.bind_plan({"actions": [action] * 65})
    with pytest.raises(ValueError):
        registry.bind_plan({"actions": []})


def test_registry_passes_one_explicit_deadline_through_compound_action():
    """内部调用传递同一期限到融合与 Follow，模型参数完全不含期限。"""

    deadlines = []

    class Device:
        """感知设备 Seam 只记录实际收到的期限。"""

        def camera(self, enabled):
            """发布请求但不假称相机硬件确认。"""
            return {"status": "real_success", "detail": "请求已发布"}

        async def set_enabled(self, kind, enabled, deadline):
            """两步服务共同消费调用者预算。"""
            deadlines.append((kind, deadline))
            return {"status": "real_success", "detail": "已确认"}

    registry = create_default_actions().registry
    registry.register_many(
        perception_actions(PerceptionActions(Device(), action_timeout=60))
    )
    plan = registry.bind_plan(
        {"actions": [{"name": "start_following", "arguments": {}}]}
    )
    deadline = time.monotonic() + 1
    receipt = asyncio.run(registry.invoke(plan.commands[0], deadline))
    assert receipt.status == "real_success"
    assert deadlines == [("fusion", deadline), ("follow", deadline)]
    assert plan.commands[0].parameters == {}
    assert "deadline" not in json.dumps(registry.tool_schema)
