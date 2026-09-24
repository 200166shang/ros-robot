"""Pure differential-drive math shared by ROS nodes and unit tests."""

from collections import namedtuple
import math


Pose2D = namedtuple('Pose2D', 'x y yaw')
Twist2D = namedtuple('Twist2D', 'linear_x angular_z')


def normalize_angle(angle):
    """Normalize radians into [-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def integrate(pose, command, delta_seconds):
    """Integrate an exact constant-twist arc for one bounded time step."""
    if delta_seconds < 0.0 or not math.isfinite(delta_seconds):
        raise ValueError('delta_seconds must be finite and non-negative')
    if not all(math.isfinite(value) for value in pose):
        raise ValueError('pose must contain only finite values')
    if not all(math.isfinite(value) for value in command):
        raise ValueError('command must contain only finite values')
    if delta_seconds == 0.0:
        return Pose2D(pose.x, pose.y, normalize_angle(pose.yaw))

    linear = command.linear_x
    angular = command.angular_z
    next_yaw = pose.yaw + angular * delta_seconds
    if abs(angular) < 1e-9:
        next_x = pose.x + linear * math.cos(pose.yaw) * delta_seconds
        next_y = pose.y + linear * math.sin(pose.yaw) * delta_seconds
    else:
        radius = linear / angular
        next_x = pose.x + radius * (math.sin(next_yaw) - math.sin(pose.yaw))
        next_y = pose.y - radius * (math.cos(next_yaw) - math.cos(pose.yaw))
    return Pose2D(next_x, next_y, normalize_angle(next_yaw))


def clamp_twist(linear_x, angular_z, max_linear, max_angular):
    """Reject non-finite input and clamp valid input to configured limits."""
    values = (linear_x, angular_z, max_linear, max_angular)
    if not all(math.isfinite(value) for value in values):
        raise ValueError('velocity and limits must be finite')
    if max_linear < 0.0 or max_angular < 0.0:
        raise ValueError('velocity limits must be non-negative')
    return Twist2D(
        clamp(linear_x, -max_linear, max_linear),
        clamp(angular_z, -max_angular, max_angular),
    )
