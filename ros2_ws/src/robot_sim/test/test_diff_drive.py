import math
import unittest

from robot_sim.diff_drive import Pose2D, Twist2D, clamp_twist, integrate, normalize_angle


class TestDifferentialDriveMath(unittest.TestCase):
    def test_straight_motion_integrates_distance(self):
        pose = integrate(Pose2D(0.0, 0.0, 0.0), Twist2D(0.5, 0.0), 2.0)
        self.assertAlmostEqual(pose.x, 1.0)
        self.assertAlmostEqual(pose.y, 0.0)
        self.assertAlmostEqual(pose.yaw, 0.0)

    def test_constant_twist_follows_exact_arc(self):
        pose = integrate(
            Pose2D(0.0, 0.0, 0.0), Twist2D(1.0, 1.0), math.pi / 2.0)
        self.assertAlmostEqual(pose.x, 1.0)
        self.assertAlmostEqual(pose.y, 1.0)
        self.assertAlmostEqual(pose.yaw, math.pi / 2.0)

    def test_reverse_motion_and_angle_wrap(self):
        pose = integrate(
            Pose2D(0.0, 0.0, math.pi - 0.1), Twist2D(-1.0, 0.2), 1.0)
        self.assertGreaterEqual(pose.yaw, -math.pi)
        self.assertLessEqual(pose.yaw, math.pi)
        self.assertAlmostEqual(normalize_angle(3.0 * math.pi), math.pi)

    def test_velocity_is_bounded(self):
        bounded = clamp_twist(4.0, -5.0, 0.25, 0.8)
        self.assertEqual(bounded, Twist2D(0.25, -0.8))

    def test_non_finite_velocity_is_rejected(self):
        with self.assertRaises(ValueError):
            clamp_twist(float('nan'), 0.0, 0.25, 0.8)

    def test_negative_time_is_rejected(self):
        with self.assertRaises(ValueError):
            integrate(Pose2D(0.0, 0.0, 0.0), Twist2D(0.0, 0.0), -0.1)


if __name__ == '__main__':
    unittest.main()
