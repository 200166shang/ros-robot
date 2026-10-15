"""原生异步文本与动作 Interface 的可观察生命周期。"""

import asyncio
import json
import ssl
import subprocess
import time

import httpx
import pytest

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.execution import ActionExecutionError
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.memory import ConversationMemory
from robot_agent.conversation.provider import (
    DashScopeProvider,
    ModelTransportError,
)
from robot_agent.results import ModelReply, ToolCall


def test_async_provider_collects_native_sse_and_closes(monkeypatch):
    """传输按异步字节收齐原生聊天，关闭后连接池已释放。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")

    async def scenario():
        """所有连接资源留在同一事件循环。"""
        requests = []

        async def transport(request):
            """只替换外部 HTTPS 服务器。"""
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                content=(
                    b'data: {"choices":[{"delta":{"content":"hello"},'
                    b'"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                ),
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        provider = DashScopeProvider({}, client=client)
        reply = await provider.complete(
            "hello",
            time.monotonic() + 1,
            tools=create_default_actions().registry.tool_schema,
        )
        assert reply.response == "hello"
        assert requests[0]["parallel_tool_calls"] is False
        await provider.aclose()
        assert client.is_closed

    asyncio.run(scenario())


def test_async_action_late_receipt_requires_reconcile_and_never_replays():
    """超时仅结束等待，原动作迟到确认，旧快照和余项保持不变。"""

    async def scenario():
        """提交与核对共用原操作所在循环。"""
        release = asyncio.Event()
        sent = []
        data = {"samples": [1]}

        class Provider:
            """外部模型固定返回完整计划。"""

            async def complete(self, text, deadline, *, tools=None):
                """保留重复计划的顺序。"""
                return ModelReply(
                    "完成",
                    ToolCall(
                        "call_async",
                        "execute_actions",
                        {
                            "actions": [
                                {"name": "device", "arguments": {}},
                                {"name": "head_nod", "arguments": {}},
                            ]
                        },
                    ),
                )

            async def aclose(self, deadline=None):
                """固定模型没有本地连接资源。"""
                pass

        async def device():
            """设备提交后只接受原调用的迟到回执。"""
            sent.append("sent")
            await release.wait()
            return {"status": "real_success", "data": data}

        registry = create_default_actions().registry
        registry.register("device", device)
        agent = Agent(Provider(), registry, action_timeout=0.02)
        first = await agent.submit("执行")
        assert [a.status for a in first.actions] == ["unknown", "not_executed"]
        assert (await agent.submit("下一轮")).status == "busy"
        assert (await agent.reconcile(first.turn_id)).actions[
            0
        ].status == "unknown"
        release.set()
        await asyncio.sleep(0)
        assert (await agent.submit("下一轮")).status == "busy"
        confirmed = await agent.reconcile(first.turn_id)
        assert [a.status for a in confirmed.actions] == [
            "real_success",
            "not_executed",
        ]
        assert confirmed.execution.tool_call_id == "call_async"
        data["samples"].append(2)
        assert confirmed.actions[0].data == {"samples": (1,)}
        assert first.actions[0].status == "unknown"
        assert sent == ["sent"]

    asyncio.run(scenario())


def test_model_retry_is_classified_finite_and_shares_phase_deadline(
    monkeypatch,
):
    """503 可重试，401 不重试，每次等待共用原阶段期限。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")

    async def scenario():
        """真实模型 Adapter 在 HTTP 外部 Seam 收到确定状态。"""
        for status, expected in [(503, 3), (401, 1)]:
            calls = []

            async def transport(request):
                """每次临时故障都消耗同一阶段预算。"""
                calls.append(time.monotonic())
                await asyncio.sleep(0.01)
                return httpx.Response(status)

            client = httpx.AsyncClient(
                transport=httpx.MockTransport(transport)
            )
            provider = DashScopeProvider({}, client=client)
            agent = Agent(
                provider,
                create_default_actions().registry,
                provider_timeout=0.2,
            )
            result = await agent.submit("hello")
            assert result.status == "failed" and result.actions == ()
            assert len(calls) == expected
            await provider.aclose()

    asyncio.run(scenario())


def test_summary_cleanup_blocks_clear_then_discards_late_summary(tmp_path):
    """摘要超时保留回复，清理结束前阻止清空，迟到摘要不能回写。"""

    async def scenario():
        """可控外部模型模拟取消期间的资源清理。"""
        release = asyncio.Event()
        cleaning = asyncio.Event()
        requests = []

        class Provider:
            """模型与摘要通过同一异步 Interface。"""

            async def complete(self, text, deadline, *, tools=None):
                """摘要取消清理结束前，禁止第二个模型请求。"""
                requests.append((text, tools))
                if "【摘要任务】" in text:
                    assert tools is None
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cleaning.set()
                        await release.wait()
                    return ModelReply("stale-summary")
                return ModelReply("confirmed-chat")

            async def aclose(self, deadline=None):
                """固定模型没有本地连接资源。"""
                pass

        memory = ConversationMemory(tmp_path / "memory", 1, 1)
        agent = Agent(
            Provider(),
            create_default_actions().registry,
            provider_timeout=0.02,
            memory=memory,
        )
        result = await agent.submit("remember-me")
        assert result.reply == "confirmed-chat"
        assert result.memory_warnings == ("summary_timeout",)
        await cleaning.wait()
        assert (await agent.clear_memory()).status == "busy"
        assert (await agent.submit("blocked")).status == "busy"
        assert len(requests) == 2
        release.set()
        await asyncio.sleep(0)
        assert (await agent.clear_memory()).status == "completed"
        assert memory.context("fresh") == "fresh"
        assert "stale-summary" not in (tmp_path / "memory").read_text()

    asyncio.run(scenario())


@pytest.mark.parametrize("error_type", [RuntimeError, RecursionError])
def test_programming_error_surfaces_with_submitted_and_confirmed_facts(
    tmp_path, error_type
):
    """设备编程错误继续抛出，之前成功与当前未知仍可供调用者保存。"""

    async def scenario():
        """失败不转成普通设备回执，也不补执行余项。"""
        sent = []

        async def broken():
            """模拟请求已发出之后的编程错误。"""
            sent.append("sent")
            raise error_type("programming failure")

        class Provider:
            """固定计划替代外部模型。"""

            async def complete(self, text, deadline, *, tools=None):
                """先即时模拟成功，再执行出现错误的设备操作。"""
                return ModelReply(
                    "done",
                    ToolCall(
                        "broken",
                        "execute_actions",
                        {
                            "actions": [
                                {"name": "head_nod", "arguments": {}},
                                {"name": "broken", "arguments": {}},
                                {"name": "head_smile", "arguments": {}},
                            ]
                        },
                    ),
                )

            async def aclose(self, deadline=None):
                """固定模型没有本地连接资源。"""
                pass

        registry = create_default_actions().registry
        registry.register("broken", broken)
        agent = Agent(Provider(), registry)
        with pytest.raises(ActionExecutionError) as failure:
            await agent.submit("go")
        assert type(failure.value.__cause__) is error_type
        assert [a.status for a in failure.value.result.actions] == [
            "simulated_success",
            "unknown",
            "not_executed",
        ]
        assert agent.last_result.actions == failure.value.result.actions
        assert (await agent.submit("again")).status == "busy"
        with pytest.raises(ActionExecutionError):
            await agent.reconcile(failure.value.result.turn_id)
        assert sent == ["sent"]

    asyncio.run(scenario())


def test_real_sse_trickle_hits_total_deadline_and_releases_socket(
    tmp_path, monkeypatch
):
    """真实 TLS SSE 受总期限约束，循环推进和连接释放可观察。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
    cert = tmp_path / "fixture.crt"
    key = tmp_path / "fixture.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    async def scenario():
        """本地 TLS 服务器只接收无效 fixture 凭证，不连接在线模型。"""
        disconnected = asyncio.Event()
        stopped = asyncio.Event()
        handlers = set()
        active = 0
        maximum = 0
        requests = 0
        ticks = 0
        warmed = False

        async def serve(reader, writer):
            """首个响应不断滴流，后续返回正常完整聊天。"""
            nonlocal active, maximum, requests
            handlers.add(asyncio.current_task())
            active += 1
            maximum = max(maximum, active)
            number = 0
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                length = next(
                    int(line.split(b":", 1)[1])
                    for line in headers.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                )
                await reader.readexactly(length)
                if not warmed:
                    warm_body = (
                        b'{"choices":[{"message":{"content":"warm"},'
                        b'"finish_reason":"stop"}]}'
                    )
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: "
                        + str(len(warm_body)).encode()
                        + b"\r\n\r\n"
                        + warm_body
                    )
                    await writer.drain()
                    headers = await reader.readuntil(b"\r\n\r\n")
                    length = next(
                        int(line.split(b":", 1)[1])
                        for line in headers.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                    await reader.readexactly(length)
                requests += 1
                number = requests
                if number == 1:
                    writer.write(
                        b"HTTP/1.1 200 OK\r\n"
                        b"Content-Type: text/event-stream\r\n"
                        b"Connection: close\r\n\r\n"
                    )
                    while True:
                        writer.write(b": heartbeat\n\n")
                        await writer.drain()
                        await asyncio.sleep(0.005)
                else:
                    body = (
                        b'{"choices":[{"message":{"content":"fresh"},'
                        b'"finish_reason":"stop"}]}'
                    )
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Length: "
                        + str(len(body)).encode()
                        + b"\r\nConnection: close\r\n\r\n"
                        + body
                    )
                    await writer.drain()
            except (OSError, asyncio.IncompleteReadError):
                pass
            finally:
                active -= 1
                writer.close()
                await writer.wait_closed()
                handlers.discard(asyncio.current_task())
                if warmed and number == 1:
                    disconnected.set()

        async def heartbeat():
            """模型等待期间循环仍能处理其他业务任务。"""
            nonlocal ticks
            while not stopped.is_set():
                ticks += 1
                await asyncio.sleep(0.002)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        server = await asyncio.start_server(serve, "127.0.0.1", 0, ssl=context)
        port = server.sockets[0].getsockname()[1]
        provider = DashScopeProvider(
            {"endpoint": "https://127.0.0.1:" + str(port)},
            client=httpx.AsyncClient(verify=False, trust_env=False),
        )
        await provider.complete("warm", time.monotonic() + 2)
        requests = 0
        warmed = True
        agent = Agent(
            provider, create_default_actions().registry, provider_timeout=0.08
        )
        ticker = asyncio.create_task(heartbeat())
        try:
            started = time.monotonic()
            result = await agent.submit("trickle")
            assert result.status == "failed" and result.actions == ()
            assert time.monotonic() - started < 0.25
            assert ticks > 3
            await asyncio.wait_for(disconnected.wait(), 1)
            for _ in range(20):
                fresh = await agent.submit("next")
                if fresh.status != "busy":
                    break
                await asyncio.sleep(0)
            assert fresh.reply == "fresh"
            assert maximum == 1 and requests == 2
        finally:
            stopped.set()
            await ticker
            await agent.aclose()
            server.close()
            await server.wait_closed()
            if handlers:
                await asyncio.gather(*tuple(handlers))

    asyncio.run(scenario())


def test_retry_attempts_share_absolute_budget_and_do_not_overlap():
    """第一次故障消耗预算，第二次只使用余量，不能重置阶段期限。"""

    async def scenario():
        """控制外部模型等待，独立观察期限与并发请求数。"""
        deadlines = []
        active = 0
        maximum = 0

        class Provider:
            """外部模型首次连接失败，下一次迟于总期限。"""

            async def complete(self, text, deadline, *, tools=None):
                """每个尝试结束后，才允许下一次连接。"""
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                deadlines.append(deadline)
                try:
                    if len(deadlines) == 1:
                        await asyncio.sleep(0.02)
                        raise ModelTransportError("network", transient=True)
                    await asyncio.sleep(0.2)
                    return ModelReply("too late")
                finally:
                    active -= 1

        agent = Agent(
            Provider(),
            create_default_actions().registry,
            provider_timeout=0.06,
        )
        started = time.monotonic()
        result = await agent.submit("hello")
        assert result.status == "failed" and result.actions == ()
        assert time.monotonic() - started < 0.15
        await asyncio.sleep(0)
        assert len(deadlines) == 2
        assert deadlines[0] == deadlines[1]
        assert maximum == 1 and active == 0

    asyncio.run(scenario())


def test_summary_programming_error_surfaces_without_erasing_action(tmp_path):
    """摘要编程错误向外显露，已确认动作仍通过回合快照可见。"""

    async def scenario():
        """错误后的清理不会重执行设备，也不会伪造记忆成功。"""
        calls = []

        class Provider:
            """先给出完整计划，摘要阶段出现意外实现错误。"""

            async def complete(self, text, deadline, *, tools=None):
                """故障是编程错误，不分类为临时网络故障。"""
                calls.append(tools)
                if tools is None:
                    raise RuntimeError("summary implementation failure")
                return ModelReply(
                    "done",
                    ToolCall(
                        "summary_error",
                        "execute_actions",
                        {"actions": [{"name": "head_nod", "arguments": {}}]},
                    ),
                )

        memory = ConversationMemory(tmp_path / "memory", 1, 1)
        agent = Agent(
            Provider(), create_default_actions().registry, memory=memory
        )
        with pytest.raises(
            RuntimeError, match="summary implementation failure"
        ):
            await agent.submit("nod")
        assert agent.last_result.actions[0].status == "simulated_success"
        assert agent.last_result.execution.tool_call_id == "summary_error"
        assert len(calls) == 2
        assert "head_nod：模拟成功" in memory.context("next")
        assert (await agent.clear_memory()).status == "completed"

    asyncio.run(scenario())


def test_model_interface_enforces_deadline_during_active_stream(monkeypatch):
    """Model 直接调用也有总期限，流持续到达不能无限延长等待。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")

    async def scenario():
        """外部流每个分片都及时到达，但整个回复永不结束。"""
        closed = asyncio.Event()

        class Stream(httpx.AsyncByteStream):
            """传输 Seam 提供永不结束的 SSE 注释流。"""

            async def __aiter__(self):
                """每次读等待都小于总预算。"""
                while True:
                    yield b": keepalive\n\n"
                    await asyncio.sleep(0.002)

            async def aclose(self, deadline=None):
                """响应退出必须释放外部流。"""
                closed.set()

        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Stream())
            )
        )
        provider = DashScopeProvider({}, client=client)
        try:
            with pytest.raises(ModelTransportError) as failure:
                await asyncio.wait_for(
                    provider.complete("hello", time.monotonic() + 0.02), 0.15
                )
            assert failure.value.code == "timeout"
            assert closed.is_set()
        finally:
            await provider.aclose()

    asyncio.run(scenario())


def test_http_response_cleanup_retains_model_ownership_until_closed(
    monkeypatch,
):
    """业务超时后 HTTP 响应清理仍有唯一归属，接入和清空均保持 busy。"""

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")

    async def scenario():
        """在实际 HTTPX 响应关闭 Seam 控制清理，而非替换 Agent 内部。"""
        release = asyncio.Event()
        cleaning = asyncio.Event()
        closed = asyncio.Event()
        requests = []

        class Stream(httpx.AsyncByteStream):
            """流始终活跃，关闭需要等本地资源释放。"""

            async def __aiter__(self):
                """总期限独立于每次分片的到达。"""
                while True:
                    yield b": heartbeat\n\n"
                    await asyncio.sleep(0.002)

            async def aclose(self, deadline=None):
                """第二次取消不得打断正在进行的同一清理。"""
                cleaning.set()
                await release.wait()
                closed.set()

        async def transport(request):
            """只替换网络端点，保留生产流与取消逻辑。"""
            requests.append(request)
            return httpx.Response(200, stream=Stream())

        client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        provider = DashScopeProvider({}, client=client)
        agent = Agent(
            provider, create_default_actions().registry, provider_timeout=0.02
        )
        try:
            result = await agent.submit("timeout")
            assert result.status == "failed" and result.actions == ()
            await cleaning.wait()
            assert not closed.is_set()
            assert (await agent.submit("overlap")).status == "busy"
            assert (await agent.clear_memory()).status == "busy"
            assert len(requests) == 1
            release.set()
            await closed.wait()
            for _ in range(20):
                cleared = await agent.clear_memory()
                if cleared.status != "busy":
                    break
                await asyncio.sleep(0)
            assert cleared.status == "completed"
        finally:
            release.set()
            await agent.aclose()
        assert client.is_closed

    asyncio.run(scenario())
