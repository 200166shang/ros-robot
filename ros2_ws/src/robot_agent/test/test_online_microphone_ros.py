"""通过ROS入口及外部音频/在线传输验证唯一麦克风逐轮流程。"""

import io
import json
import time

import rclpy
import websocket
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from test_online_speech import SpeechSocket

from robot_agent.ros.voice_node import OnlineVoiceRosNode


def test_microphone_is_only_input_and_turns_resume_in_order(
    tmp_path, monkeypatch
) -> None:
    """正常入口没有文本订阅，麦克风唤醒、动作、休眠逐轮完成。"""
    gate = tmp_path / "capture-ready"
    recorder = tmp_path / "record-fixture"
    recorder.write_text(
        "#!/usr/bin/python3\n"
        "import sys, time, wave\n"
        "from pathlib import Path\n"
        f"while not Path({str(gate)!r}).exists(): time.sleep(0.01)\n"
        "time.sleep(0.1)\n"
        "with wave.open(sys.argv[-1], 'wb') as wav:\n"
        "    wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))\n"
        "    wav.writeframes(bytes(3200))\n",
        encoding="utf-8",
    )
    recorder.chmod(0o755)
    texts = iter(["小沫小沫", "请点头", "晚安"])
    model_inputs = []
    sockets = []

    class MicrophoneSocket(SpeechSocket):
        """替换WSS外部事件，保留ASR/TTS真实协议及回合交接。"""

        def send(self, raw):
            """为每轮录音提供一个最终句，TTS沿用原音频事件。"""
            command = json.loads(raw)
            if (
                command["header"]["action"] == "finish-task"
                and self.kind == "asr"
            ):
                text = next(texts, "")
                self.event(
                    "result-generated",
                    {
                        "output": {
                            "sentence": {
                                "text": text,
                                "sentence_end": True,
                                "heartbeat": False,
                            }
                        }
                    },
                )
                self.event("task-finished")
            else:
                super().send(raw)

    def connect(endpoint, header, timeout):
        """在线传输在外部Seam替换，生产组装与会话不替换。"""
        socket = MicrophoneSocket()
        sockets.append(socket)
        return socket

    def complete(request, timeout):
        """固定模型建议点头，观察只有有效麦克风请求进入模型。"""
        model_inputs.append(
            json.loads(request.data)["messages"][-1]["content"]
        )
        reply = json.dumps({"function": ["head_nod"], "response": "已完成"})
        event = {"choices": [{"delta": {"content": reply}}]}
        return io.BytesIO(
            ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n").encode()
        )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setattr(websocket, "create_connection", connect)
    monkeypatch.setattr("urllib.request.urlopen", complete)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "output_dir": str(tmp_path / "results"),
                "memory_file": str(tmp_path / "memory.json"),
                "record_executable": str(recorder),
                "record_device": "fixture",
                "record_seconds": 1,
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
        assert results[2]["session_state"] == "standby"
    finally:
        # 3. 生产退出Interface取消录音并回收唯一业务线程。
        agent.stop()
        executor.shutdown()
        agent.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()
    assert all(socket.closed for socket in sockets)
