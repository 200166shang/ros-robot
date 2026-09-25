import json
import threading
from concurrent.futures import ThreadPoolExecutor

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Bool, String

from robot_interfaces.action import HeadMotion
from robot_interfaces.msg import HeadState
from robot_head.catalog import MOTION_CATALOG
from .navigation_client import (
    DEFAULT_NAV2_ENDPOINT,
    NAVIGATION_COMMAND_TO_LOCATION,
    NAVIGATION_MODEL_FUNCTIONS,
    NAVIGATION_TERMINAL_STATUSES,
    NavigationClientError,
    NavigationHttpClient,
)


class CommandAgent(Node):
    """Fixed-command executor; head functions target simulation, never hardware."""

    def __init__(self):
        super().__init__('command_agent')
        self.simulation_mode = bool(
            self.declare_parameter('simulation_mode', False).value)
        self.enable_simulated_navigation = bool(
            self.declare_parameter('enable_simulated_navigation', False).value)
        self.camera_enabled = not self.simulation_mode
        self.tracking_enabled = False
        self._head_lock = threading.RLock()
        self._head_state = None
        self._active_head_command = None
        self._head_goal_handle = None
        self._navigation_lock = threading.RLock()
        self._navigation_state = {
            'enabled': self.enable_simulated_navigation,
            'simulated': True,
            'backend': 'nav2-jazzy-loopback',
            'status': 'idle',
            'task_id': None,
            'location_id': None,
            'location_label': None,
            'error': None,
            'gateway_available': self.enable_simulated_navigation,
        }
        self._active_navigation_task_id = None
        self._navigation_submission_pending = False
        self._navigation_worker = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix='simulated-nav')
        self._navigation_stop = threading.Event()
        self._navigation_poll_thread = None
        self._navigation_client = None
        if self.enable_simulated_navigation:
            endpoint = self.declare_parameter(
                'nav2_http_endpoint', DEFAULT_NAV2_ENDPOINT
            ).value
            timeout = self.declare_parameter(
                'navigation_http_timeout_seconds', 2.0
            ).value
            self._navigation_client = NavigationHttpClient(
                str(endpoint), float(timeout))
            self.navigation_state_pub = self.create_publisher(
                String, '/agent/navigation/state', 10)
            self._navigation_poll_thread = threading.Thread(
                target=self._poll_navigation_loop,
                name='simulated-nav-status',
                daemon=True)
            self._navigation_poll_thread.start()
        self.camera_pub = self.create_publisher(Bool, '/enable_camera', 10)
        self.tracking_pub = self.create_publisher(Bool, '/enable_tracking', 10)
        self.sim_control_source_pub = self.create_publisher(
            String, '/robot/sim/control_source', 10)
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
            'head backend=sim (no servo/GPIO); Nav2 simulation=%s' %
            ('enabled' if self.enable_simulated_navigation else 'disabled'))

    def destroy_node(self):
        self._navigation_stop.set()
        if self._navigation_poll_thread is not None:
            self._navigation_poll_thread.join(timeout=2.5)
        self._navigation_worker.shutdown(wait=True)
        return super().destroy_node()

    def publish_bool(self, publisher, value):
        message = Bool()
        message.data = value
        publisher.publish(message)

    def set_sim_control_source(self, source):
        if not self.simulation_mode:
            return
        message = String()
        message.data = source
        self.sim_control_source_pub.publish(message)

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
            'safe_output_topic': (
                '/robot/sim/tracking_cmd_vel'
                if self.simulation_mode else '/tracking/cmd_vel_safe'
            ),
        }
        if self.simulation_mode:
            payload['backend'] = 'sim'
            payload['simulated'] = True
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

        if command in NAVIGATION_MODEL_FUNCTIONS.values():
            if not self.enable_simulated_navigation:
                self.respond(command, False, 'Nav2 仿真技能未显式启用。')
                return
            self._navigation_worker.submit(
                self.handle_navigation_command, command)
            return

        if self.simulation_mode and command in ('start_camera', 'stop_camera'):
            self.respond(
                command, False,
                '当前启动的是虚拟人物仿真，没有真实摄像头可启停。')
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
            self.camera_enabled = not self.simulation_mode
            self.tracking_enabled = True
            if not self.simulation_mode:
                self.publish_bool(self.camera_pub, True)
            self.publish_bool(self.tracking_pub, True)
            self.set_sim_control_source('tracking')
        elif command == 'stop_tracking':
            self.tracking_enabled = False
            self.publish_bool(self.tracking_pub, False)
            self.set_sim_control_source('stop')
        elif command != 'status':
            self.respond(command, False, 'unsupported command')
            return
        self.respond(command)

    def _navigation_snapshot(self):
        with self._navigation_lock:
            return dict(self._navigation_state)

    def _publish_navigation_state(self, state=None):
        if not self.enable_simulated_navigation:
            return
        payload = self._navigation_snapshot() if state is None else dict(state)
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.navigation_state_pub.publish(message)

    def handle_navigation_command(self, command):
        """Run one fixed simulated-navigation command off the ROS callback."""
        if command in NAVIGATION_COMMAND_TO_LOCATION:
            with self._navigation_lock:
                if self._navigation_submission_pending or self._active_navigation_task_id:
                    active = dict(self._navigation_state)
                    self.respond(
                        command, False,
                        '已有导航任务尚未结束。',
                        extra={'navigation': active})
                    return
                self._navigation_submission_pending = True
                self._navigation_state.update({
                    'status': 'submitting', 'error': None,
                    'location_id': NAVIGATION_COMMAND_TO_LOCATION[command],
                    'location_label': '模拟目标 A' if command.endswith('goal_a') else '模拟目标 B',
                    'gateway_available': True,
                })
            try:
                task = self._navigation_client.start_navigation(
                    NAVIGATION_COMMAND_TO_LOCATION[command])
            except NavigationClientError as error:
                with self._navigation_lock:
                    self._navigation_submission_pending = False
                    self._navigation_state.update({
                        'status': 'failed', 'task_id': None,
                        'error': str(error), 'gateway_available': False,
                    })
                    failed_state = dict(self._navigation_state)
                self._publish_navigation_state(failed_state)
                self.respond(command, False, str(error),
                             extra={'navigation': failed_state})
                return
            with self._navigation_lock:
                self._navigation_submission_pending = False
                self._active_navigation_task_id = task['task_id']
                self._navigation_state.update({
                    'status': task['status'],
                    'task_id': task['task_id'],
                    'location_id': task['location_id'],
                    'error': None,
                    'gateway_available': True,
                })
                state = dict(self._navigation_state)
            self._publish_navigation_state(state)
            self.respond(command, extra={'navigation': state})
            return

        if command == 'cancel_navigation':
            with self._navigation_lock:
                task_id = self._active_navigation_task_id
                state = dict(self._navigation_state)
            if task_id is None:
                self.respond(command, False, '当前没有可取消的导航任务。',
                             extra={'navigation': state})
                return
            try:
                self._navigation_client.cancel_navigation(task_id)
            except NavigationClientError as error:
                self.respond(command, False, str(error), extra={'navigation': state})
                return
            with self._navigation_lock:
                self._navigation_state.update({
                    'status': 'canceling', 'error': None,
                    'gateway_available': True,
                })
                state = dict(self._navigation_state)
            self._publish_navigation_state(state)
            self.respond(command, extra={'navigation': state})
            return

        with self._navigation_lock:
            state = dict(self._navigation_state)
        self.respond(command, extra={'navigation': state})

    def _poll_navigation_loop(self):
        """Refresh task feedback independently of user-command callbacks."""
        while not self._navigation_stop.wait(1.5):
            with self._navigation_lock:
                task_id = self._active_navigation_task_id
            if task_id is None:
                continue
            try:
                task = self._navigation_client.get_task(task_id)
            except NavigationClientError as error:
                with self._navigation_lock:
                    self._navigation_state.update({
                        'gateway_available': False,
                        'error': str(error),
                    })
                    state = dict(self._navigation_state)
                self._publish_navigation_state(state)
                continue

            with self._navigation_lock:
                self._navigation_state.update({
                    'status': task['status'],
                    'location_id': task['location_id'],
                    'location_label': task.get('location_label') or
                        self._navigation_state['location_label'],
                    'distance_remaining_m': task.get('distance_remaining_m'),
                    'error': task.get('error'),
                    'gateway_available': True,
                })
                if task['status'] in NAVIGATION_TERMINAL_STATUSES:
                    self._active_navigation_task_id = None
                state = dict(self._navigation_state)
            self._publish_navigation_state(state)


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
