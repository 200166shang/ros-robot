"""ROS action server that simulates fixed head motions without hardware access."""

import threading
import time
import uuid

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from robot_interfaces.action import HeadMotion
from robot_interfaces.msg import HeadState

from .catalog import MOTION_CATALOG, motion_duration, pose_at


class HeadMotionNode(Node):
    def __init__(self):
        super().__init__('robot_head_motion')
        backend = self.declare_parameter('backend', 'sim').value
        if backend != 'sim':
            raise ValueError('robot_head_motion only supports backend=sim')

        self._lock = threading.RLock()
        self._reserved_motion = None
        self._state = {
            'motion': '',
            'phase': 'idle',
            'expression': '正常',
            'pitch_deg': 90.0,
            'yaw_deg': 90.0,
            'motion_id': '',
            'message': '虚拟头部空闲，未连接实体舵机。',
        }
        self._state_publisher = self.create_publisher(
            HeadState, '/robot/head/state', 10)
        self._state_timer = self.create_timer(0.5, self._publish_state)
        self._action_server = ActionServer(
            self,
            HeadMotion,
            '/robot/head_motion',
            execute_callback=self.execute_motion,
            goal_callback=self.on_goal,
            cancel_callback=self.on_cancel,
            callback_group=ReentrantCallbackGroup(),
        )
        self.get_logger().info(
            'virtual head ready at /robot/head_motion (simulated; no servo/GPIO)')

    def on_goal(self, request):
        if request.motion not in MOTION_CATALOG:
            self.get_logger().warning('rejected unknown virtual head motion')
            return GoalResponse.REJECT
        with self._lock:
            if self._reserved_motion is not None:
                return GoalResponse.REJECT
            self._reserved_motion = request.motion
        return GoalResponse.ACCEPT

    def on_cancel(self, _goal_handle):
        return CancelResponse.ACCEPT

    def _set_state(self, **values):
        with self._lock:
            self._state.update(values)
        self._publish_state()

    def _publish_state(self):
        with self._lock:
            snapshot = dict(self._state)
        message = HeadState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.backend = 'sim'
        message.motion = snapshot['motion']
        message.phase = snapshot['phase']
        message.expression = snapshot['expression']
        message.pitch_deg = float(snapshot['pitch_deg'])
        message.yaw_deg = float(snapshot['yaw_deg'])
        message.simulated = True
        message.motion_id = snapshot['motion_id']
        message.message = snapshot['message']
        self._state_publisher.publish(message)

    def execute_motion(self, goal_handle):
        motion = goal_handle.request.motion
        spec = MOTION_CATALOG[motion]
        motion_id = uuid.uuid4().hex
        duration = motion_duration(motion)
        started = time.monotonic()
        result = HeadMotion.Result()
        self._set_state(
            motion=motion,
            phase='moving',
            expression=spec.expression,
            motion_id=motion_id,
            message='正在网页端渲染虚拟头部动作；未驱动实体舵机。',
        )
        try:
            while True:
                elapsed = time.monotonic() - started
                pitch, yaw = pose_at(motion, elapsed)
                self._set_state(pitch_deg=pitch, yaw_deg=yaw)

                feedback = HeadMotion.Feedback()
                feedback.motion = motion
                feedback.phase = 'moving'
                feedback.expression = spec.expression
                feedback.pitch_deg = float(pitch)
                feedback.yaw_deg = float(yaw)
                feedback.simulated = True
                feedback.motion_id = motion_id
                goal_handle.publish_feedback(feedback)

                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.success = False
                    result.message = '虚拟动作已取消。'
                    self._set_state(
                        phase='cancelled',
                        message=result.message + '当前姿态仅为仿真值。',
                    )
                    break
                if elapsed >= duration:
                    goal_handle.succeed()
                    result.success = True
                    result.message = '虚拟动作完成；未驱动实体舵机。'
                    self._set_state(
                        pitch_deg=spec.waypoints[-1][0],
                        yaw_deg=spec.waypoints[-1][1],
                        phase='completed',
                        message=result.message,
                    )
                    break
                time.sleep(0.1)
        finally:
            with self._lock:
                self._reserved_motion = None

        result.backend = 'sim'
        result.expression = spec.expression
        with self._lock:
            result.pitch_deg = float(self._state['pitch_deg'])
            result.yaw_deg = float(self._state['yaw_deg'])
        result.simulated = True
        result.motion_id = motion_id
        return result


def main(args=None):
    rclpy.init(args=args)
    node = HeadMotionNode()
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
