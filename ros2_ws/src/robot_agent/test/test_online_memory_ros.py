"""通过真实 ROS 话题和固定 HTTPS 响应验证记忆接入。"""

import io
import json
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from robot_agent.online_ros_node import OnlineRosNode


def test_ros_text_memory_and_clear(tmp_path, monkeypatch):
    """话题输入能带上近期上下文，明确 clear 指令清空两种记忆。"""
    requests = []

    def send(request, timeout):
        """在外部 HTTPS 出口提供固定流式响应。"""
        body = json.loads(request.data)
        requests.append(body["messages"][-1]["content"])
        reply = json.dumps({"function": [], "response": "收到"})
        event = {"choices": [{"delta": {"content": reply}}]}
        return io.BytesIO(
            ("data: " + json.dumps(event) + "\n\ndata: [DONE]\n").encode()
        )

    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixed-test-key")
    monkeypatch.setattr("urllib.request.urlopen", send)
    config = tmp_path / "online.json"
    config.write_text(
        json.dumps({"memory_file": str(tmp_path / "memory.json")}),
        encoding="utf-8",
    )
    rclpy.init(args=["--ros-args", "-p", "config_file:=" + str(config)])
    agent = OnlineRosNode()
    probe = Node("memory_test_probe")
    executor = SingleThreadedExecutor()
    executor.add_node(agent)
    executor.add_node(probe)
    results = []

    def receive(message):
        """从公开结果话题接收交互回执。"""
        results.append(json.loads(message.data))

    probe.create_subscription(String, "/online_agent/result", receive, 10)
    text = probe.create_publisher(String, "/online_agent/text", 10)
    clear = probe.create_publisher(String, "/online_agent/clear_memory", 10)

    def publish(publisher, content):
        """等待发现完成后提交，并等待一条可观察回执。"""
        deadline = time.monotonic() + 5
        while publisher.get_subscription_count() == 0:
            assert time.monotonic() < deadline, "ROS 订阅发现超时"
            executor.spin_once(timeout_sec=0.01)
        count = len(results)
        message = String()
        message.data = content
        publisher.publish(message)
        while len(results) == count:
            assert time.monotonic() < deadline, "ROS 回执超时"
            executor.spin_once(timeout_sec=0.01)
        assert results[-1]["status"] == "completed"
        assert not results[-1]["memory_warnings"]

    try:
        publish(text, "recent-marker")
        publish(text, "继续聊天")
        assert "recent-marker" in requests[-1]
        publish(clear, "clear")
        publish(text, "重新聊天")
        assert requests[-1] == "重新聊天"
    finally:
        agent.stop()
        executor.shutdown()
        agent.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()
