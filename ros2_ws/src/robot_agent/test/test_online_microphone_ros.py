"""通过ROS入口及外部音频/在线传输验证唯一麦克风逐轮流程。"""

import asyncio
import json
import threading
import time

import rclpy
import websocket
from async_speech_fixture import acknowledge, final
from native_protocol_fixture import install_async_transport, native_response
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from test_online_speech import SpeechSocket
from websockets.asyncio import client, server

from robot_agent.ros.voice_node import OnlineVoiceRosNode


def test_microphone_is_only_input_and_turns_resume_in_order(
    tmp_path, monkeypatch
) -> None:
    """正常入口没有文本订阅，麦克风唤醒、动作、休眠逐轮完成。"""
    gate = tmp_path / "capture-ready"
    recorder = tmp_path / "record-fixture"
    recorder.write_text(
        "#!/usr/bin/python3\n"
        "import sys, time\n"
        "from pathlib import Path\n"
        f"while not Path({str(gate)!r}).exists(): time.sleep(0.01)\n"
        "while True:\n"
        "    sys.stdout.buffer.write(b'\\x01\\x00' * 1600)\n"
        "    sys.stdout.buffer.flush()\n"
        "    time.sleep(0.02)\n",
        encoding="utf-8",
    )
    recorder.chmod(0o755)
    playing = tmp_path / "playback-active"
    player = tmp_path / "play-fixture"
    player.write_text(
        "#!/usr/bin/python3\nimport time\nfrom pathlib import Path\n"
        f"active = Path({str(playing)!r})\n"
        "active.touch()\ntime.sleep(.08)\nactive.unlink()\n"
    )
    player.chmod(0o755)
    texts = iter(["小沫小沫", "请点头", "晚安"])
    model_inputs = []
    sockets = []

    ready = True
    asr_sockets = []
    asr_frames = []
    pause_frames = []

    class MicrophoneSocket(SpeechSocket):
        """临时TTS Adapter的同步外部传输，持续输入使用原生socket。"""

        def send(self, raw):
            """TTS完成前观察持续ASR静音保活。"""
            nonlocal ready
            super().send(raw)
            command = json.loads(raw)
            if command["header"]["action"] == "finish-task":
                count = len(asr_frames)
                deadline = time.monotonic() + 1
                while len(asr_frames) < count + 2:
                    assert time.monotonic() < deadline
                    time.sleep(0.005)
                pause_frames.extend(asr_frames[-2:])
                ready = True

    async def recognize(socket):
        """真实原生WebSocket接收PCM，仅新音频触发下一句。"""
        nonlocal ready
        command = await acknowledge(socket)
        asr_sockets.append(command)
        async for frame in socket:
            asr_frames.append(frame)
            if playing.exists():
                assert frame == bytes(3200), "播放期间不能发送真实麦克风音频"
            if frame != bytes(3200) and ready:
                text = next(texts, "")
                if text:
                    ready = False
                    await final(
                        socket, command, text, (len(asr_frames) - 1) * 100
                    )

    server_loop = asyncio.new_event_loop()
    server_ready = threading.Event()
    stop_server = []
    server_ports = []

    async def serve():
        """本机服务器独占自己的事件循环，ROS入口仍用真实生产组装。"""
        async with server.serve(recognize, "127.0.0.1", 0) as listener:
            server_ports.append(listener.sockets[0].getsockname()[1])
            stop_server.append(asyncio.Event())
            server_ready.set()
            await stop_server[0].wait()

    def run_server():
        """fixture线程只运行外部语音服务器，不参与业务状态。"""
        server_loop.run_until_complete(serve())
        server_loop.close()

    server_thread = threading.Thread(target=run_server)
    server_thread.start()
    assert server_ready.wait(2)
    native_connect = client.connect

    def connect_asr(uri, **kwargs):
        """将生产WSS连接路由到本机原生WebSocket fixture。"""
        return native_connect(f"ws://127.0.0.1:{server_ports[0]}", **kwargs)

    monkeypatch.setattr(client, "connect", connect_asr)

    def connect(endpoint, header, timeout):
        """在线传输在外部Seam替换，生产组装与会话不替换。"""
        socket = MicrophoneSocket()
        sockets.append(socket)
        return socket

    def complete(request, timeout):
        """固定模型建议点头，观察只有有效麦克风请求进入模型。"""
        model_inputs.append(
            json.loads(request.content)["messages"][-1]["content"]
        )
        return native_response([{"name": "head_nod", "arguments": {}}])

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
    monkeypatch.setattr(websocket, "create_connection", connect)
    install_async_transport(monkeypatch, complete)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "output_dir": str(tmp_path / "results"),
                "memory_file": str(tmp_path / "memory.json"),
                "record_executable": str(recorder),
                "record_device": "fixture",
                "playback_enabled": True,
                "play_executable": str(player),
                "play_device": "fixture",
            }
        ),
        encoding="utf-8",
    )
    rclpy.init(args=["--ros-args", "-p", "config_file:=" + str(config)])
    probe = Node("single_microphone_test")
    results = []

    def receive(message):
        """从生产公开话题观察完整语音回执。"""
        results.append(json.loads(message.data))

    probe.create_subscription(String, "/online_agent/result", receive, 10)
    agent = OnlineVoiceRosNode()
    executor = SingleThreadedExecutor()
    executor.add_node(probe)
    executor.add_node(agent)
    try:
        subscriptions = agent.get_subscriber_names_and_types_by_node(
            agent.get_name(), agent.get_namespace()
        )
        assert not any(
            topic.startswith("/online_agent/") for topic, _ in subscriptions
        )
        assert not agent.has_parameter("dry_run")
        # 1. 发现结果订阅后才开放外部录音源，避免丢失首轮回执。
        deadline = time.monotonic() + 5
        while probe.count_publishers("/online_agent/result") == 0:
            assert time.monotonic() < deadline
            executor.spin_once(timeout_sec=0.01)
        gate.touch()
        # 2. 三轮均经录音/ASR，上一轮完整合成后才接入下一轮。
        while len(results) < 3:
            assert time.monotonic() < deadline, results
            executor.spin_once(timeout_sec=0.01)
        assert [result["status"] for result in results[:3]] == [
            "woken",
            "completed",
            "sleeping",
        ]
        assert model_inputs == ["请点头"]
        assert results[1]["actions"][0]["status"] == "simulated_success"
        assert all(r["tts_status"] == "completed" for r in results[:3])
        assert all(r["playback_status"] == "completed" for r in results[:3])
        assert results[2]["session_state"] == "standby"
        assert len(asr_sockets) == 1
        assert asr_sockets[0]["header"]["action"] == "run-task"
        assert pause_frames == [bytes(3200)] * 6
    finally:
        # 3. 生产退出Interface取消录音并回收唯一业务线程。
        agent.stop()
        executor.shutdown()
        agent.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()
        server_loop.call_soon_threadsafe(stop_server[0].set)
        server_thread.join(2)
        assert not server_thread.is_alive()
    assert all(socket.closed for socket in sockets)
