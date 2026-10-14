"""通过 ROS 话题验收在线聊天与模拟动作，配置和凭证外置。"""

import json
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from robot_agent.online_ros_node import OnlineRosNode


def main() -> None:
    """启动真实 ROS 入口，顺序发布两轮文本并断言关联结果。"""
    rclpy.init()
    agent = OnlineRosNode()
    probe = Node("online_text_acceptance_probe")
    executor = SingleThreadedExecutor()
    executor.add_node(agent)
    executor.add_node(probe)
    results = []

    def receive(message: String) -> None:
        """保存公开话题回执作为验收证据。"""
        results.append(json.loads(message.data))

    probe.create_subscription(String, "/online_agent/result", receive, 10)
    publisher = probe.create_publisher(String, "/online_agent/text", 10)
    try:
        deadline = time.monotonic() + 10
        while (
            publisher.get_subscription_count() == 0
            and time.monotonic() < deadline
        ):
            executor.spin_once(timeout_sec=0.1)
        assert publisher.get_subscription_count() > 0, "文本订阅未就绪"

        for text in (
            "你好，请简短介绍你自己，不做动作。",
            "请依次点头、微笑、再点头。",
        ):
            expected_count = len(results) + 1
            message = String()
            message.data = text
            publisher.publish(message)
            deadline = time.monotonic() + 75
            while (
                len(results) < expected_count and time.monotonic() < deadline
            ):
                executor.spin_once(timeout_sec=0.1)
            assert len(results) == expected_count, "ROS 回合无回执"

        assert (
            results[0]["status"] == "completed" and not results[0]["actions"]
        )
        assert results[1]["status"] == "completed"
        assert [a["name"] for a in results[1]["actions"]] == [
            "head_nod",
            "head_smile",
            "head_nod",
        ]
        assert all(
            a["status"] == "simulated_success" for a in results[1]["actions"]
        )
        assert results[0]["turn_id"] != results[1]["turn_id"]
        # 已完成回合的核对请求应明确拒绝，不能重发动作。
        reconcile = probe.create_publisher(
            String, "/online_agent/reconcile", 10
        )
        deadline = time.monotonic() + 10
        while (
            reconcile.get_subscription_count() == 0
            and time.monotonic() < deadline
        ):
            executor.spin_once(timeout_sec=0.1)
        assert reconcile.get_subscription_count() > 0, "核对订阅未就绪"
        message = String()
        message.data = results[1]["turn_id"]
        reconcile.publish(message)
        deadline = time.monotonic() + 10
        while len(results) < 3 and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.1)
        assert len(results) == 3
        assert results[2]["turn_id"] == results[1]["turn_id"]
        assert results[2]["status"] == "rejected" and not results[2]["actions"]
        print(json.dumps(results, ensure_ascii=False))
    finally:
        agent.stop()
        executor.shutdown()
        agent.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
