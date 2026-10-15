"""本地原生WebSocket传输fixture，保持生产鉴权与协议处理。"""

import json
from contextlib import asynccontextmanager

from websockets.asyncio import client, server


@asynccontextmanager
async def speech_server(monkeypatch, handler, **options):
    """仅将加密外部端点路由到本机，消息仍走真实异步socket。"""
    connect = client.connect
    async with server.serve(handler, "127.0.0.1", 0, **options) as listener:
        port = listener.sockets[0].getsockname()[1]

        def local_connect(uri, **kwargs):
            """保留生产连接参数，包括Authorization。"""
            return connect(f"ws://127.0.0.1:{port}", **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setenv("DASHSCOPE_API_KEY", "fixture-only")
            scoped.setattr(client, "connect", local_connect)
            yield scoped


async def acknowledge(socket):
    """接收run-task并发送相同标识的握手回执。"""
    command = json.loads(await socket.recv())
    assert socket.request.headers["Authorization"] == "Bearer fixture-only"
    await event(socket, command, "task-started")
    return command


async def event(socket, command, kind, payload=None):
    """发送具有本任务标识的服务端事件。"""
    await socket.send(
        json.dumps(
            {
                "header": {
                    "task_id": command["header"]["task_id"],
                    "event": kind,
                },
                "payload": payload or {},
            }
        )
    )


async def final(socket, command, text, begin=0):
    """提供独立的最终句测试数据。"""
    await event(
        socket,
        command,
        "result-generated",
        {
            "output": {
                "sentence": {
                    "text": text,
                    "begin_time": begin,
                    "sentence_end": True,
                    "heartbeat": False,
                }
            },
        },
    )
