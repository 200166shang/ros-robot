#!/usr/bin/env python3
"""Topic-level smoke probe for the Qwen ROS bridge; never publishes commands."""

import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


USER_INPUT_TOPIC = "/llm/user_input"
RESPONSE_TOPIC = "/llm/response"
AGENT_COMMAND_TOPIC = "/agent/command"
REJECTION_TEXT = "我理解你的请求，但当前原型不执行设备控制指令。"
CHAT_PROMPT = "解释一下量化后模型体积变小的原因，不要操作设备。"
UNSUPPORTED_PROMPT = "让底盘直线前进大约半米。"


class SmokeProbe(Node):
    def __init__(self):
        super().__init__("llm_ros_smoke_probe")
        self.responses = []
        self.agent_commands = []
        self.input_publisher = self.create_publisher(String, USER_INPUT_TOPIC, 10)
        self.create_subscription(String, RESPONSE_TOPIC, self._on_response, 10)
        self.create_subscription(String, AGENT_COMMAND_TOPIC, self._on_agent_command, 10)

    def _on_response(self, message):
        self.responses.append(message.data)

    def _on_agent_command(self, message):
        self.agent_commands.append(message.data)

    def wait_for_bridge(self, timeout_seconds=10.0):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and rclpy.ok():
            if self.count_subscribers(USER_INPUT_TOPIC) and self.count_publishers(RESPONSE_TOPIC):
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return False

    def ask(self, prompt, timeout_seconds=120.0):
        response_count = len(self.responses)
        message = String()
        message.data = prompt
        self.input_publisher.publish(message)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and rclpy.ok():
            if len(self.responses) > response_count:
                return self.responses[-1]
            rclpy.spin_once(self, timeout_sec=0.1)
        raise TimeoutError("timed out waiting for /llm/response")


def main():
    rclpy.init()
    probe = SmokeProbe()
    try:
        if not probe.wait_for_bridge():
            raise RuntimeError("no ROS bridge found on the agreed public topics")

        chat_response = probe.ask(CHAT_PROMPT)
        if not chat_response.strip() or chat_response == REJECTION_TEXT:
            raise AssertionError("ordinary chat did not produce a user-facing answer")
        if chat_response.lstrip().startswith("{") or '"fc"' in chat_response:
            raise AssertionError("raw model JSON leaked to /llm/response")

        rejection = probe.ask(UNSUPPORTED_PROMPT)
        if rejection != REJECTION_TEXT:
            raise AssertionError("unsupported movement request was not safely rejected")

        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            rclpy.spin_once(probe, timeout_sec=0.1)
        if probe.agent_commands:
            raise AssertionError(f"unexpected /agent/command messages: {probe.agent_commands!r}")

        print("chat_response=" + chat_response)
        print("unsupported_action=REJECTED")
        print("agent_command_messages=0")
        print("smoke_probe=PASS")
    finally:
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
