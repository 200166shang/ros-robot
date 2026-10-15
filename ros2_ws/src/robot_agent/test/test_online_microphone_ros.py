"""通过ROS入口及外部音频/在线传输验证唯一麦克风逐轮流程。"""

import asyncio
import json
import os
import signal
import threading
import time
from contextlib import contextmanager

import rclpy
from async_speech_fixture import acknowledge, event, final, speech_server
from native_protocol_fixture import install_async_transport, native_response
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import SetBool

from robot_agent.ros.voice_node import OnlineVoiceRosNode, RosExecutor, main


@contextmanager
def native_asr_server(monkeypatch, handler):
    """本机语音服务器拥有独立循环，公共主入口仍可拥有应用主循环。"""
    ready = threading.Event()
    control = []

    async def serve():
        """复用原生语音fixture，在接纳应用前完成外部端点路由。"""
        async with speech_server(monkeypatch, handler):
            stop = asyncio.Event()
            control.append((asyncio.get_running_loop(), stop))
            ready.set()
            await stop.wait()

    def run_server():
        """线程只接收外部测试服务的协议消息，不运行应用。"""
        asyncio.run(serve())

    worker = threading.Thread(target=run_server, name="fixture-asr-server")
    worker.start()
    assert ready.wait(2), "本机语音fixture未启动"
    try:
        yield
    finally:
        loop, stop = control[0]
        loop.call_soon_threadsafe(stop.set)
        worker.join(2)
        assert not worker.is_alive()


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
    texts = iter(["小沫小沫", "跟随并点头", "晚安"])
    model_inputs = []
    tts_commands = []
    tts_closed = []

    ready = True
    asr_sockets = []
    asr_frames = []
    pause_frames = []

    async def recognize(socket):
        """真实原生 socket 接收 PCM，只有恢复后的新音频触发下一句。"""
        nonlocal ready
        command = await acknowledge(socket)
        if command["payload"]["task"] == "tts":
            tts_commands.append(command)
            text = json.loads(await socket.recv())
            assert text["header"]["action"] == "continue-task"
            finish = json.loads(await socket.recv())
            assert finish["header"]["action"] == "finish-task"
            count = len(asr_frames)
            deadline = time.monotonic() + 1
            while len(asr_frames) < count + 2:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.005)
            pause_frames.extend(asr_frames[-2:])
            await socket.send(bytes(4800))
            await event(socket, command, "task-finished")
            ready = True
            await socket.wait_closed()
            tts_closed.append(True)
            return
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

    def complete(request, timeout):
        """固定模型建议感知与模拟动作，只处理有效麦克风请求。"""
        model_inputs.append(
            json.loads(request.content)["messages"][-1]["content"]
        )
        return native_response(
            [
                {"name": "start_following", "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ]
        )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
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

    async def run():
        """主事件循环拥有节点应用，独立 executor 接收结果。"""
        rclpy.init(args=["--ros-args", "-p", "config_file:=" + str(config)])
        probe = Node("single_microphone_test")
        results = []
        device_events = []

        def camera(message):
            """受控采集端只记录请求，不声称硬件状态。"""
            device_events.append(("camera", message.data))

        def follow(request, response):
            """本地 Follow 测试服务器代替真实设备。"""
            device_events.append(("follow", request.data))
            response.success = True
            response.message = "fixture Follow confirmed"
            return response

        def fusion(request, response):
            """本地融合测试服务器不接入传感器或运动出口。"""
            device_events.append(("fusion", request.data))
            response.success = True
            response.message = "fixture fusion confirmed"
            return response

        probe.create_subscription(Bool, "/enable_camera", camera, 10)
        probe.create_service(SetBool, "/tracking/set_enabled", follow)
        probe.create_service(SetBool, "/tracking/set_lidar_enabled", fusion)

        def receive(message):
            """从生产公开话题观察完整语音回执。"""
            results.append(json.loads(message.data))

        probe.create_subscription(String, "/online_agent/result", receive, 10)
        agent = OnlineVoiceRosNode()
        assert tts_commands == [] and asr_sockets == []
        executor = RosExecutor(probe, agent)
        executor.start()
        application = asyncio.create_task(agent.run())
        try:
            subscriptions = agent.get_subscriber_names_and_types_by_node(
                agent.get_name(), agent.get_namespace()
            )
            assert not any(
                topic.startswith("/online_agent/")
                for topic, _ in subscriptions
            )
            assert not agent.has_parameter("dry_run")
            # 1. 发现结果订阅后才开放外部录音源，避免丢失首轮回执。
            deadline = time.monotonic() + 5
            while (
                probe.count_publishers("/online_agent/result") == 0
                or agent.count_subscribers("/enable_camera") == 0
                or "/tracking/set_lidar_enabled"
                not in dict(agent.get_service_names_and_types())
            ):
                assert time.monotonic() < deadline
                await asyncio.sleep(0.01)
            gate.touch()
            # 2. 三轮均经录音/ASR，上一轮完整合成后才接入下一轮。
            while len(results) < 3:
                assert time.monotonic() < deadline, results
                await asyncio.sleep(0.01)
            assert [result["status"] for result in results[:3]] == [
                "woken",
                "completed",
                "sleeping",
            ]
            assert model_inputs == ["跟随并点头"]
            assert [a["status"] for a in results[1]["actions"]] == [
                "real_success",
                "simulated_success",
            ]
            assert device_events.count(("camera", True)) == 1
            assert device_events.count(("fusion", True)) == 1
            assert device_events.count(("follow", True)) == 1
            assert all(r["tts_status"] == "completed" for r in results[:3])
            assert all(
                r["playback_status"] == "completed" for r in results[:3]
            )
            assert results[2]["session_state"] == "standby"
            assert len(asr_sockets) == 1
            assert asr_sockets[0]["header"]["action"] == "run-task"
            assert pause_frames == [bytes(3200)] * 6
        finally:
            # 3. 生产退出 Interface 关闭应用后再回收 ROS executor。
            deadline = time.monotonic() + 2
            await agent.aclose(deadline)
            await application
            await executor.aclose(deadline)
            agent.destroy_node()
            probe.destroy_node()
            rclpy.shutdown()
        assert len(tts_commands) == 3
        assert tts_closed == [True] * 3

    with native_asr_server(monkeypatch, recognize):
        asyncio.run(run())


def test_node_constructor_keeps_business_and_recording_idle(
    tmp_path, monkeypatch
):
    """构造只接线；启动由主事件循环的明确调用控制。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"output_dir": str(tmp_path / "results")}))
    rclpy.init(args=["--ros-args", "-p", "config_file:=" + str(config)])
    before = set(threading.enumerate())
    node = OnlineVoiceRosNode()
    try:
        assert set(threading.enumerate()) == before
    finally:
        asyncio.run(node.aclose(time.monotonic() + 1))
        node.destroy_node()
        rclpy.shutdown()


def test_main_sigint_closes_application_before_ros(tmp_path, monkeypatch):
    """Foxy 主入口收到 SIGINT 后按顺序关闭输入、应用与 executor。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixture-only")
    recorder = tmp_path / "idle-recorder"
    recorder.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(60)\n")
    recorder.chmod(0o755)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "output_dir": str(tmp_path / "results"),
                "record_executable": str(recorder),
                "record_device": "fixture",
            }
        )
    )
    connected = threading.Event()
    disconnected = threading.Event()

    async def recognize(socket):
        """真实握手到达后发送 SIGINT，验证在途原生连接收尾。"""
        await acknowledge(socket)
        connected.set()
        os.kill(os.getpid(), signal.SIGINT)
        await socket.wait_closed()
        disconnected.set()

    def unexpected_model(request, timeout):
        """此场景不提供最终句；意外模型调用也不能访问外网。"""
        raise AssertionError("没有最终句时不应请求模型")

    install_async_transport(monkeypatch, unexpected_model)
    before = set(threading.enumerate())
    with native_asr_server(monkeypatch, recognize):
        # 握手失败仍可退出，connected 断言保留原生链路失败证据。
        interrupt = threading.Timer(
            2, lambda: os.kill(os.getpid(), signal.SIGINT)
        )
        interrupt.start()
        try:
            main(["--ros-args", "-p", "config_file:=" + str(config)])
        finally:
            interrupt.cancel()
            interrupt.join()
        assert connected.is_set()
        assert disconnected.wait(1)
    assert not rclpy.ok()
    assert not [
        thread
        for thread in set(threading.enumerate()) - before
        if thread.name == "online-ros-executor"
    ]
