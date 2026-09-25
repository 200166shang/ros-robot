import unittest

from robot_head.catalog import MOTION_CATALOG, MODEL_FUNCTIONS, catalog_payload, motion_duration, pose_at


class TestHeadMotionCatalog(unittest.TestCase):
    def test_every_profile_stays_within_original_servo_software_bounds(self):
        for name, spec in MOTION_CATALOG.items():
            with self.subTest(name=name):
                self.assertGreaterEqual(motion_duration(name), 0.0)
                self.assertEqual(spec.waypoints[0][2], 0.0)
                self.assertEqual(tuple(sorted(point[2] for point in spec.waypoints)),
                                 tuple(point[2] for point in spec.waypoints))
                for pitch, yaw, _ in spec.waypoints:
                    self.assertGreaterEqual(pitch, 65)
                    self.assertLessEqual(pitch, 120)
                    self.assertGreaterEqual(yaw, 50)
                    self.assertLessEqual(yaw, 130)

    def test_interpolation_and_end_clamping(self):
        pitch, yaw = pose_at('head_nod', 0.225)
        self.assertAlmostEqual(pitch, 96.5)
        self.assertAlmostEqual(yaw, 90.0)
        self.assertEqual(pose_at('head_nod', 100), (90.0, 90.0))

    def test_catalog_payload_has_only_fixed_simulation_profiles(self):
        payload = catalog_payload()
        self.assertEqual({entry['name'] for entry in payload}, MODEL_FUNCTIONS)
        self.assertTrue(all(entry['simulated'] for entry in payload))


if __name__ == '__main__':
    unittest.main()
