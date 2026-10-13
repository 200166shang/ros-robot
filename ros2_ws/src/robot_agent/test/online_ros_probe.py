"""Exercise ROS input/reply/action topics with deterministic or real provider."""

from __future__ import annotations

import argparse
import json
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from robot_agent.online_agent import OnlineAgent, SimulatedDevices
from robot_agent.online_provider import OnlineProvider, load_config
from robot_agent.online_ros_node import OnlineRosNode


class FixedProvider:
    """为 ROS 收发探针提供确定的协议响应。"""

    def complete(self, text: str) -> str:
        """根据输入返回聊天或模拟音量动作响应。"""
        return json.dumps(
            {
                "function": ["volume_set(30)"] if "音量" in text else [],
                "response": "我会模拟设置音量。" if "音量" in text else "你好。",
            }
        )


def main() -> None:
    """通过 ROS 主题验证普通聊天和模拟动作的输入到回复链路。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="external configuration; omit for fixed responses")
    options = parser.parse_args()
    provider = OnlineProvider(load_config(options.config)) if options.config else FixedProvider()
    rclpy.init()
    agent_node = OnlineRosNode(OnlineAgent(provider, SimulatedDevices()))
    observer = Node("online_agent_probe")
    results, replies, events = [], [], []
    observer.create_subscription(
        String,
        "/online_agent/result",
        lambda msg: results.append(json.loads(msg.data)),
        10,
    )
    observer.create_subscription(String, "/online_agent/response", lambda msg: replies.append(msg.data), 10)
    observer.create_subscription(
        String,
        "/online_agent/action_events",
        lambda msg: events.append(json.loads(msg.data)),
        10,
    )
    publisher = observer.create_publisher(String, "/online_agent/user_input", 10)
    executor = SingleThreadedExecutor()
    executor.add_node(agent_node)
    executor.add_node(observer)
    try:
        deadline = time.monotonic() + 10
        while publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.1)
        for index, text in enumerate(
            [
                "你好，请普通聊天，不执行任何动作。",
                "请执行模拟 volume_set(30) 动作。设置音量。",
            ]
        ):
            message = String()
            message.data = text
            publisher.publish(message)
            deadline = time.monotonic() + 90
            while len(results) <= index and time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.1)
        deadline = time.monotonic() + 5
        while (len(replies) < 2 or not events) and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.1)
        assert len(results) == 2 and all(result["success"] for result in results), results
        assert not results[0]["actions"] and results[0]["response"]
        assert results[1]["actions"] and all(action["simulated"] for action in results[1]["actions"])
        assert events and len(replies) == 2
        print(
            json.dumps(
                {
                    "mode": "real_online" if options.config else "fixed_provider",
                    "results": results,
                    "reply_count": len(replies),
                    "action_event_count": len(events),
                },
                ensure_ascii=False,
            )
        )
    finally:
        executor.shutdown()
        agent_node.destroy_node()
        observer.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
