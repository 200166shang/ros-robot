import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String


class CommandAgent(Node):
    """Small deterministic function executor; no cloud, motors, lidar, GPIO or shell calls."""

    def __init__(self):
        super().__init__('command_agent')
        self.camera_enabled = True
        self.tracking_enabled = False
        self.camera_pub = self.create_publisher(Bool, '/enable_camera', 10)
        self.tracking_pub = self.create_publisher(Bool, '/enable_tracking', 10)
        self.response_pub = self.create_publisher(String, '/agent/response', 10)
        self.command_sub = self.create_subscription(String, '/agent/command', self.on_command, 10)
        self.get_logger().info('commands: start_camera, stop_camera, start_tracking, stop_tracking, status')

    def publish_bool(self, publisher, value):
        message = Bool()
        message.data = value
        publisher.publish(message)

    def respond(self, command, success=True, error=None):
        payload = {
            'command': command,
            'success': success,
            'camera_enabled': self.camera_enabled,
            'tracking_enabled': self.tracking_enabled,
            'safe_output_topic': '/tracking/cmd_vel_safe',
        }
        if error:
            payload['error'] = error
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.response_pub.publish(message)
        self.get_logger().info(message.data)

    def on_command(self, message):
        raw = message.data.strip()
        try:
            parsed = json.loads(raw) if raw.startswith('{') else {'command': raw}
            command = str(parsed.get('command', '')).strip()
        except (ValueError, TypeError) as exc:
            self.respond(raw, False, f'invalid JSON: {exc}')
            return

        if command == 'start_camera':
            self.camera_enabled = True
            self.publish_bool(self.camera_pub, True)
        elif command == 'stop_camera':
            self.camera_enabled = False
            self.tracking_enabled = False
            self.publish_bool(self.tracking_pub, False)
            self.publish_bool(self.camera_pub, False)
        elif command == 'start_tracking':
            self.camera_enabled = True
            self.tracking_enabled = True
            self.publish_bool(self.camera_pub, True)
            self.publish_bool(self.tracking_pub, True)
        elif command == 'stop_tracking':
            self.tracking_enabled = False
            self.publish_bool(self.tracking_pub, False)
        elif command != 'status':
            self.respond(command, False, 'unsupported command')
            return
        self.respond(command)


def main(args=None):
    rclpy.init(args=args)
    node = CommandAgent()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
