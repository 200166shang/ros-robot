import json
import threading

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool, String

from robot_interfaces.action import HeadMotion
from robot_interfaces.msg import HeadState
from robot_head.catalog import MOTION_CATALOG


class CommandAgent(Node):
    """Fixed-command executor; head functions target simulation, never hardware."""

    def __init__(self):
        super().__init__('command_agent')
        self.camera_enabled = True
        self.tracking_enabled = False
        self._head_lock = threading.RLock()
        self._head_state = None
        self._active_head_command = None
        self._head_goal_handle = None
        self.camera_pub = self.create_publisher(Bool, '/enable_camera', 10)
        self.tracking_pub = self.create_publisher(Bool, '/enable_tracking', 10)
        self.response_pub = self.create_publisher(String, '/agent/response', 10)
        self.command_sub = self.create_subscription(String, '/agent/command', self.on_command, 10)
        self.head_state_sub = self.create_subscription(
            HeadState, '/robot/head/state', self.on_head_state, 10)
        self._head_callback_group = ReentrantCallbackGroup()
        self.head_client = ActionClient(
            self, HeadMotion, '/robot/head_motion',
            callback_group=self._head_callback_group)
        self.get_logger().info(
            'commands: camera/tracking/status plus fixed virtual-head motions; '
            'head backend=sim (no servo/GPIO)')

    def publish_bool(self, publisher, value):
        message = Bool()
        message.data = value
        publisher.publish(message)

    def on_head_state(self, message):
        with self._head_lock:
            self._head_state = {
                'backend': message.backend,
                'motion': message.motion,
                'phase': message.phase,
                'expression': message.expression,
                'pitch_deg': round(float(message.pitch_deg), 1),
                'yaw_deg': round(float(message.yaw_deg), 1),
                'simulated': bool(message.simulated),
                'motion_id': message.motion_id,
                'message': message.message,
            }

    def head_state_snapshot(self):
        with self._head_lock:
            return None if self._head_state is None else dict(self._head_state)

    def respond(self, command, success=True, error=None, extra=None):
        payload = {
            'command': command,
            'success': success,
            'camera_enabled': self.camera_enabled,
            'tracking_enabled': self.tracking_enabled,
            'safe_output_topic': '/tracking/cmd_vel_safe',
        }
        head_state = self.head_state_snapshot()
        if head_state is not None:
            payload['head_state'] = head_state
            payload['backend'] = head_state['backend']
            payload['simulated'] = head_state['simulated']
        if extra:
            payload.update(extra)
        if error:
            payload['error'] = error
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.response_pub.publish(message)
        self.get_logger().info(message.data)

    def start_head_motion(self, command):
        with self._head_lock:
            if self._active_head_command is not None:
                self.respond(command, False, 'another virtual head motion is active')
                return
            if not self.head_client.server_is_ready():
                self.respond(command, False, 'virtual head simulator is not online')
                return
            self._active_head_command = command

        goal = HeadMotion.Goal()
        goal.motion = command
        try:
            future = self.head_client.send_goal_async(goal)
            future.add_done_callback(
                lambda completed: self.on_head_goal_response(command, completed))
        except Exception as error:
            self.clear_head_motion(command)
            self.respond(command, False, 'failed to submit virtual motion')
            self.get_logger().error(
                'head goal submit failed ({})'.format(type(error).__name__))

    def on_head_goal_response(self, command, future):
        try:
            goal_handle = future.result()
        except Exception as error:
            self.clear_head_motion(command)
            self.respond(command, False, 'virtual head simulator did not accept request')
            self.get_logger().error(
                'head goal response failed ({})'.format(type(error).__name__))
            return
        if not goal_handle.accepted:
            self.clear_head_motion(command)
            self.respond(command, False, 'virtual head motion was rejected or is busy')
            return
        with self._head_lock:
            self._head_goal_handle = goal_handle
        goal_handle.get_result_async().add_done_callback(
            lambda completed: self.on_head_result(command, completed))

    def on_head_result(self, command, future):
        try:
            wrapped_result = future.result()
            result = wrapped_result.result
            success = bool(result.success)
            details = {
                'backend': result.backend,
                'simulated': bool(result.simulated),
                'head_motion_id': result.motion_id,
                'head_state': {
                    'backend': result.backend,
                    'motion': command,
                    'phase': 'completed' if success else 'cancelled',
                    'expression': result.expression,
                    'pitch_deg': round(float(result.pitch_deg), 1),
                    'yaw_deg': round(float(result.yaw_deg), 1),
                    'simulated': bool(result.simulated),
                    'motion_id': result.motion_id,
                    'message': result.message,
                },
            }
            self.clear_head_motion(command)
            self.respond(
                command, success,
                None if success else result.message,
                extra=details)
        except Exception as error:
            self.clear_head_motion(command)
            self.respond(command, False, 'virtual head motion result unavailable')
            self.get_logger().error(
                'head result failed ({})'.format(type(error).__name__))

    def clear_head_motion(self, command):
        with self._head_lock:
            if self._active_head_command == command:
                self._active_head_command = None
                self._head_goal_handle = None

    def cancel_head_motion(self):
        with self._head_lock:
            goal_handle = self._head_goal_handle
            command = self._active_head_command
        if goal_handle is None or command is None:
            self.respond('head_cancel', False, 'no active virtual head motion')
            return
        try:
            goal_handle.cancel_goal_async().add_done_callback(
                self.on_head_cancel_response)
        except Exception as error:
            self.respond('head_cancel', False, 'could not cancel virtual motion')
            self.get_logger().error(
                'head cancel failed ({})'.format(type(error).__name__))

    def on_head_cancel_response(self, future):
        try:
            response = future.result()
            accepted = bool(response.goals_canceling)
        except Exception:
            accepted = False
        self.respond(
            'head_cancel', accepted,
            None if accepted else 'virtual head motion did not accept cancellation')

    def on_command(self, message):
        raw = message.data.strip()
        try:
            parsed = json.loads(raw) if raw.startswith('{') else {'command': raw}
            if not isinstance(parsed, dict):
                raise ValueError('command must be a JSON object')
            command_value = parsed.get('command', '')
            if not isinstance(command_value, str):
                raise ValueError('command name must be text')
            command = command_value.strip()
        except (ValueError, TypeError) as exc:
            self.respond(raw, False, f'invalid JSON: {exc}')
            return

        if command in MOTION_CATALOG:
            if set(parsed) != {'command'}:
                self.respond(command, False, 'virtual motions do not accept parameters')
                return
            self.start_head_motion(command)
            return
        if command == 'head_cancel':
            self.cancel_head_motion()
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
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
