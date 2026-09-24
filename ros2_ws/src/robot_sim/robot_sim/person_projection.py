"""Deterministic pinhole projection for a virtual person in the 2D world."""

import math


def project_person(robot_x, robot_y, robot_yaw, person_x, person_y,
                   image_width=640, image_height=360, horizontal_fov_deg=70.0,
                   person_height_m=1.65, max_range_m=8.0):
    """Return a synthetic detection box, or None when the person is not visible."""
    values = (robot_x, robot_y, robot_yaw, person_x, person_y,
              horizontal_fov_deg, person_height_m, max_range_m)
    if not all(math.isfinite(value) for value in values):
        raise ValueError('projection values must be finite')
    if image_width < 16 or image_height < 16:
        raise ValueError('image dimensions are too small')
    if not 1.0 < horizontal_fov_deg < 179.0:
        raise ValueError('horizontal field of view must be between 1 and 179 degrees')
    if person_height_m <= 0.0 or max_range_m <= 0.0:
        raise ValueError('person height and maximum range must be positive')

    delta_x = person_x - robot_x
    delta_y = person_y - robot_y
    forward = math.cos(robot_yaw) * delta_x + math.sin(robot_yaw) * delta_y
    lateral = -math.sin(robot_yaw) * delta_x + math.cos(robot_yaw) * delta_y
    distance = math.hypot(forward, lateral)
    bearing = math.atan2(lateral, forward)
    half_fov = math.radians(horizontal_fov_deg) * 0.5
    if forward <= 0.2 or distance > max_range_m or abs(bearing) > half_fov:
        return None

    focal = (image_width * 0.5) / math.tan(half_fov)
    center_x = image_width * 0.5 - focal * lateral / forward
    box_height = min(image_height * 0.9, focal * person_height_m / forward)
    box_width = max(8.0, box_height * 0.38)
    center_y = image_height * 0.53
    x1 = max(0, int(math.floor(center_x - box_width * 0.5)))
    x2 = min(image_width, int(math.ceil(center_x + box_width * 0.5)))
    y1 = max(0, int(math.floor(center_y - box_height * 0.5)))
    y2 = min(image_height, int(math.ceil(center_y + box_height * 0.5)))
    if x2 <= x1 or y2 <= y1:
        return None
    return {
        'x1': x1,
        'y1': y1,
        'x2': x2,
        'y2': y2,
        'center_x': center_x,
        'range_m': distance,
        'bearing_rad': bearing,
    }
