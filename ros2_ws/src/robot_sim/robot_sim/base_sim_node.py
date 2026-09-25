"""Differential-drive simulator isolated from hardware command topics."""

import math
import time

import rclpy
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster

from robot_interfaces.msg import BaseState

from .diff_drive import Pose2D, Twist2D, clamp_twist, integrate


class BaseSimulationNode(Node):
    """Simulate a differential-drive base with bounded, leased commands."""

    COMMAND_TOPICS = {
        'manual': '/robot/sim/manual_cmd_vel',
        'tracking': '/robot/sim/tracking_cmd_vel',
        'navigation': '/robot/sim/navigation_cmd_vel',
    }
    CONTROL_SOURCES = frozenset(tuple(COMMAND_TOPICS) + ('stop',))

    def __init__(self):
        super().__init__('robot_base_sim')
        backend = self.declare_parameter('backend', 'sim').value
        if backend != 'sim':
            raise ValueError('robot_base_sim only supports backend=sim')

        self.max_linear = float(self.declare_parameter('max_linear_mps', 0.25).value)
        self.max_angular = float(self.declare_parameter('max_angular_rps', 0.8).value)
        self.command_timeout = float(
            self.declare_parameter('command_timeout_sec', 0.5).value)
        self.publish_rate = float(self.declare_parameter('publish_rate_hz', 30.0).value)
        for name, value in (
                ('max_linear_mps', self.max_linear),
                ('max_angular_rps', self.max_angular),
                ('command_timeout_sec', self.command_timeout),
                ('publish_rate_hz', self.publish_rate)):
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError('{} must be a positive finite number'.format(name))

        self.true_pose = Pose2D(0.0, 0.0, 0.0)
        self.odom_pose = Pose2D(0.0, 0.0, 0.0)
        self.commands = {
            source: {'twist': Twist2D(0.0, 0.0), 'received_at': 0.0}
            for source in self.COMMAND_TOPICS
        }
        self.control_source = 'manual'
        self._last_tick = time.monotonic()
        self._state_publisher = self.create_publisher(
            BaseState, '/robot/sim/base_state', 10)
        self._odom_publisher = self.create_publisher(
            Odometry, '/robot/sim/odom', 10)
        self._ground_truth_publisher = self.create_publisher(
            Odometry, '/robot/sim/ground_truth', 10)
        self._tf_broadcaster = TransformBroadcaster(self)

        self._subscriptions = []
        for source, topic in self.COMMAND_TOPICS.items():
            self._subscriptions.append(self.create_subscription(
                Twist, topic,
                lambda message, name=source: self._on_command(name, message),
                10))
        self._subscriptions.append(self.create_subscription(
            String, '/robot/sim/control_source', self._on_control_source, 10))
        self._timer = self.create_timer(1.0 / self.publish_rate, self._tick)
        self.get_logger().info(
            'base simulator ready; inputs restricted to /robot/sim/*_cmd_vel; '
            'real /cmd_vel and hardware topics are not subscribed')

    def _on_control_source(self, message):
        requested = message.data.strip()
        if requested not in self.CONTROL_SOURCES:
            self.get_logger().warning('ignored unsupported simulation control source')
            return
        self.control_source = requested
        if requested == 'stop':
            self._clear_commands()

    def _on_command(self, source, message):
        try:
            bounded = clamp_twist(
                float(message.linear.x), float(message.angular.z),
                self.max_linear, self.max_angular)
        except (TypeError, ValueError):
            self.get_logger().warning('ignored non-finite simulation velocity')
            return
        self.commands[source] = {
            'twist': bounded,
            'received_at': time.monotonic(),
        }

    def _clear_commands(self):
        for command in self.commands.values():
            command['twist'] = Twist2D(0.0, 0.0)
            command['received_at'] = 0.0

    @staticmethod
    def _quaternion(yaw):
        return (0.0, 0.0, math.sin(yaw * 0.5), math.cos(yaw * 0.5))

    def _publish_odometry(self, pose, twist, stamp, frames, publisher):
        message = Odometry()
        message.header.stamp = stamp
        message.header.frame_id, message.child_frame_id = frames
        message.pose.pose.position.x = pose.x
        message.pose.pose.position.y = pose.y
        qx, qy, qz, qw = self._quaternion(pose.yaw)
        message.pose.pose.orientation.x = qx
        message.pose.pose.orientation.y = qy
        message.pose.pose.orientation.z = qz
        message.pose.pose.orientation.w = qw
        message.twist.twist.linear.x = twist.linear_x
        message.twist.twist.angular.z = twist.angular_z
        publisher.publish(message)

    def _publish_tf(self, stamp):
        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = 'sim_odom'
        transform.child_frame_id = 'sim_base_link'
        transform.transform.translation.x = self.odom_pose.x
        transform.transform.translation.y = self.odom_pose.y
        qx, qy, qz, qw = self._quaternion(self.odom_pose.yaw)
        transform.transform.rotation.x = qx
        transform.transform.rotation.y = qy
        transform.transform.rotation.z = qz
        transform.transform.rotation.w = qw
        self._tf_broadcaster.sendTransform(transform)

    def _tick(self):
        now = time.monotonic()
        delta = max(0.0, min(now - self._last_tick, 0.2))
        self._last_tick = now
        command_info = self.commands.get(self.control_source)
        received_at = 0.0 if command_info is None else command_info['received_at']
        expired = (
            self.control_source == 'stop' or received_at == 0.0
            or now - received_at > self.command_timeout
        )
        command = Twist2D(0.0, 0.0) if expired else command_info['twist']
        self.true_pose = integrate(self.true_pose, command, delta)
        # Phase C starts with ideal odometry. Phase F introduces estimate noise.
        self.odom_pose = self.true_pose
        stamp = self.get_clock().now().to_msg()
        self._publish_odometry(
            self.odom_pose, command, stamp,
            ('sim_odom', 'sim_base_link'), self._odom_publisher)
        self._publish_odometry(
            self.true_pose, command, stamp,
            ('sim_world', 'sim_ground_truth'), self._ground_truth_publisher)
        self._publish_tf(stamp)

        state = BaseState()
        state.header.stamp = stamp
        state.header.frame_id = 'sim_world'
        state.backend = 'sim'
        state.control_source = self.control_source
        state.ground_truth_x = self.true_pose.x
        state.ground_truth_y = self.true_pose.y
        state.ground_truth_yaw = self.true_pose.yaw
        state.odom_x = self.odom_pose.x
        state.odom_y = self.odom_pose.y
        state.odom_yaw = self.odom_pose.yaw
        state.linear_x = command.linear_x
        state.angular_z = command.angular_z
        state.command_timed_out = expired
        state.simulated = True
        self._state_publisher.publish(state)


def main(args=None):
    rclpy.init(args=args)
    node = BaseSimulationNode()
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
