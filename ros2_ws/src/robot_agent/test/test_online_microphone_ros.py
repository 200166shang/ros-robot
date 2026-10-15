"""通过ROS入口及外部音频/在线传输验证唯一麦克风逐轮流程。"""

import asyncio
import json
import os
import signal
import threading
import time

import rclpy
import websocket
from native_protocol_fixture import install_async_transport, native_response
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import SetBool
from test_online_speech import SpeechSocket

from robot_agent.ros.voice_node import OnlineVoiceRosNode, RosExecutor, main


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
    sockets = []

    ready = True
    asr_sockets = []
    pause_frames = []

    class MicrophoneSocket(SpeechSocket):
        """替换WSS事件，保留持续PCM、ASR保活与TTS真实协议。"""

        def send(self, raw):
            """ASR任务跨三轮；TTS期间必须继续发送静音。"""
            nonlocal ready
            super().send(raw)
            command = json.loads(raw)
            if (
                command["header"]["action"] == "run-task"
                and self.kind == "asr"
            ):
                asr_sockets.append(self)
            if (
                command["header"]["action"] == "finish-task"
                and self.kind == "tts"
            ):
                count = len(asr_sockets[0].frames)
                deadline = time.monotonic() + 1
                while len(asr_sockets[0].frames) < count + 2:
                    assert time.monotonic() < deadline
                    time.sleep(0.005)
                pause_frames.extend(asr_sockets[0].frames[-2:])
                ready = True

        def send_binary(self, frame):
            """只有恢复后的真实音频才产生下一句，不依赖finish-task。"""
            nonlocal ready
            super().send_binary(frame)
            if self.kind == "asr" and playing.exists():
                assert frame == bytes(3200), "播放期间不能发送真实麦克风音频"
            if self.kind == "asr" and frame != bytes(3200) and ready:
                text = next(texts, "")
                if not text:
                    return
                ready = False
                self.event(
                    "result-generated",
                    {
                        "output": {
                            "sentence": {
                                "text": text,
                                "begin_time": (len(self.frames) - 1) * 100,
                                "sentence_end": True,
                                "heartbeat": False,
                            }
                        }
                    },
                )

    def connect(endpoint, header, timeout):
        """在线传输在外部Seam替换，生产组装与会话不替换。"""
        socket = MicrophoneSocket()
        sockets.append(socket)
        return socket

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

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
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
        assert sockets == []
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
            assert len(asr_sockets[0].commands) == 1
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
        assert all(socket.closed for socket in sockets)

    asyncio.run(run())


def test_node_constructor_keeps_business_and_recording_idle(
    tmp_path, monkeypatch
):
    """构造只接线；启动由主事件循环的明确调用控制。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
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
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
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
    sockets = []

    def connect(*args, **kwargs):
        """只打开受控语音协议替身，不调用在线服务。"""
        socket = SpeechSocket()
        sockets.append(socket)
        return socket

    monkeypatch.setattr(websocket, "create_connection", connect)
    before = set(threading.enumerate())
    interrupt = threading.Timer(
        0.5, lambda: os.kill(os.getpid(), signal.SIGINT)
    )
    interrupt.start()
    try:
        main(["--ros-args", "-p", "config_file:=" + str(config)])
    finally:
        interrupt.cancel()
        interrupt.join()
    assert not rclpy.ok()
    assert all(socket.closed for socket in sockets)
    assert not [
        thread
        for thread in set(threading.enumerate()) - before
        if thread.name == "online-ros-executor"
    ]
