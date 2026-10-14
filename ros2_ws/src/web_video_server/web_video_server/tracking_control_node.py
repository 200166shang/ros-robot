"""网页设备控制：独立于模型桥接，使用已有相机话题及 Follow 服务。"""

import json
from typing import List, Optional

import rclpy
from rclpy.node import Node
from rclpy.publisher import Publisher
from rclpy.task import Future
from std_msgs.msg import Bool, String
from std_srvs.srv import SetBool


class TrackingControlNode(Node):
    """处理有限命令集，不直接调用云端、底盘、电机、GPIO 或 Shell。"""

    def __init__(self) -> None:
        """接入网页控制话题，保留现有相机及跟随服务契约。"""
        super().__init__("tracking_control", parameter_overrides=[])
        self.camera_enabled = True
        self.tracking_enabled = False
        self.camera_pub = self.create_publisher(Bool, "/enable_camera", 10)
        self.tracking_client = self.create_client(
            SetBool,
            "/tracking/set_enabled",
        )
        self.response_pub = self.create_publisher(
            String, "/web/control_result", 10
        )
        self.command_sub = self.create_subscription(
            String,
            "/web/control",
            self.on_command,
            10,
        )
        self.get_logger().info(
            "commands: start_camera, stop_camera, start_tracking, "
            "stop_tracking, status"
        )

    def publish_bool(self, publisher: Publisher, value: bool) -> None:
        """发布相机开关，不控制物理运动。"""
        message = Bool()
        message.data = value
        publisher.publish(message)

    def respond(
        self, command: str, success: bool = True, error: Optional[str] = None
    ) -> None:
        """发布设备控制结果，只汇报已确认的软件状态。"""
        payload = {
            "command": command,
            "success": success,
            "camera_enabled": self.camera_enabled,
            "tracking_enabled": self.tracking_enabled,
            "safe_output_topic": "/tracking/cmd_vel_safe",
        }
        if error:
            payload["error"] = error
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.response_pub.publish(message)
        self.get_logger().info(message.data)

    def request_tracking_state(self, command: str, enabled: bool) -> None:
        """请求 Follow 状态变更，并反馈控制服务不可用的情况。"""
        if not self.tracking_client.service_is_ready():
            self.respond(
                command, False, "tracking control service is unavailable"
            )
            return

        request = SetBool.Request()
        request.data = enabled
        future = self.tracking_client.call_async(request)
        future.add_done_callback(
            lambda result: self.on_tracking_response(command, enabled, result)
        )

    def on_tracking_response(
        self, command: str, enabled: bool, future: Future
    ) -> None:
        """处理控制服务响应，并仅在成功时更新 Follow 状态。"""
        try:
            response = future.result()
        except Exception as error:  # noqa: BLE001
            self.respond(command, False, f"tracking service failed: {error}")
            return

        if response is None:
            self.respond(
                command, False, "tracking service returned no response"
            )
            return
        if not response.success:
            self.respond(command, False, response.message)
            return

        self.tracking_enabled = enabled
        self.respond(command)

    def on_command(self, message: String) -> None:
        """校验网页有限命令并交给已有设备接口。"""
        # 1. 校验网页输入，设备控制仅接受固定命令集合。
        raw = message.data.strip()
        try:
            parsed = (
                json.loads(raw) if raw.startswith("{") else {"command": raw}
            )
            command = str(parsed.get("command", "")).strip()
        except (ValueError, TypeError) as exc:
            self.respond(raw, False, f"invalid JSON: {exc}")
            return

        # 2. 按命令交给既有设备接口，Follow 只采纳服务确认。
        if command == "start_camera":
            self.camera_enabled = True
            self.publish_bool(self.camera_pub, True)
        elif command == "stop_camera":
            self.camera_enabled = False
            self.publish_bool(self.camera_pub, False)
            self.request_tracking_state(command, False)
            return
        elif command == "start_tracking":
            # 2.1 先恢复相机采集，再请求 Follow；保持原有交接顺序。
            self.camera_enabled = True
            self.publish_bool(self.camera_pub, True)
            self.request_tracking_state(command, True)
            return
        elif command == "stop_tracking":
            self.request_tracking_state(command, False)
            return
        elif command != "status":
            self.respond(command, False, "unsupported command")
            return
        self.respond(command)


def main(args: Optional[List[str]] = None) -> None:
    """运行独立网页控制入口并释放 ROS 资源。"""
    # 1. 建立 ROS 控制入口并进入事件循环。
    rclpy.init(args=args)
    node = TrackingControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 2. 退出时释放节点及 ROS 上下文。
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
