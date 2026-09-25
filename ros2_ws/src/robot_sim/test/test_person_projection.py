import math
import unittest

from robot_sim.person_projection import project_person


class TestVirtualPersonProjection(unittest.TestCase):
    def test_person_ahead_projects_near_image_center(self):
        box = project_person(0, 0, 0, 3, 0)
        self.assertIsNotNone(box)
        self.assertAlmostEqual(box['center_x'], 320)
        self.assertAlmostEqual(box['range_m'], 3)

    def test_person_on_left_projects_left_for_positive_tracking_turn(self):
        box = project_person(0, 0, 0, 3, 0.5)
        self.assertLess(box['center_x'], 320)
        self.assertGreater(320 - box['center_x'], 0)

    def test_robot_turn_changes_projection_and_error_direction(self):
        initial = project_person(0, 0, 0, 3, 0.5)
        turned = project_person(0, 0, math.radians(8), 3, 0.5)
        self.assertIsNotNone(initial)
        self.assertIsNotNone(turned)
        self.assertNotAlmostEqual(initial['center_x'], turned['center_x'])
        self.assertLess(abs(turned['center_x'] - 320),
                        abs(initial['center_x'] - 320))

    def test_target_behind_or_outside_fov_is_hidden(self):
        self.assertIsNone(project_person(0, 0, 0, -1, 0))
        self.assertIsNone(project_person(0, 0, 0, 0, 2))

    def test_invalid_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            project_person(0, 0, 0, 3, 0, image_width=8)


if __name__ == '__main__':
    unittest.main()
