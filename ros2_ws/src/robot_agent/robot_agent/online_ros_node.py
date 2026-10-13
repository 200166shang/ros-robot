"""ROS text Adapter for the Online Agent. No actuator publishers are created."""

import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .online_agent import OnlineAgent, SimulatedDevices
from .online_provider import OnlineProvider, load_config


class OnlineRosNode(Node):
    def __init__(self, agent=None):
        super().__init__("online_agent")
        path = self.declare_parameter("config_file", "").value
        self._agent = (
            agent
            if agent is not None
            else OnlineAgent(OnlineProvider(load_config(path)), SimulatedDevices())
        )
        self._reply = self.create_publisher(String, "/online_agent/response", 10)
        self._events = self.create_publisher(String, "/online_agent/action_events", 10)
        self._results = self.create_publisher(String, "/online_agent/result", 10)
        self.create_subscription(String, "/online_agent/user_input", self._on_text, 10)
        self.get_logger().info(
            "Online Agent ready; all implemented device actions are simulated"
        )

    def _on_text(self, message):
        result = self._agent.submit(message.data)
        for action in result["actions"]:
            self._publish(self._events, json.dumps(action, ensure_ascii=False))
        self._publish(self._reply, result["response"])
        self._publish(self._results, json.dumps(result, ensure_ascii=False))

    @staticmethod
    def _publish(publisher, text):
        message = String()
        message.data = text
        publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = OnlineRosNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    except Exception:
        # Avoid printing provider errors or configuration values with secrets.
        print(
            "Online Agent startup failed: check external configuration and credentials."
        )
        raise SystemExit(1) from None
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
