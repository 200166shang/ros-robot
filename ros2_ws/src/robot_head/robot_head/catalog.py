"""Single source of truth for fixed, hardware-free XiaoMo head motions."""

from collections import namedtuple


Motion = namedtuple('Motion', 'label expression waypoints')

# Each waypoint is (pitch degrees, yaw degrees, seconds from motion start).
# Bounds preserve the original servo controller's conservative software range,
# but this module only describes browser-rendered simulation state.
MOTION_CATALOG = {
    'head_smile': Motion('开心表情', '微笑', ((90, 90, 0.0), (90, 90, 0.8))),
    'head_nod': Motion('点头', '兴奋', ((90, 90, 0.0), (103, 90, 0.45),
                                       (79, 90, 0.9), (98, 90, 1.35), (90, 90, 1.8))),
    'head_shake': Motion('摇头', '正常', ((90, 90, 0.0), (90, 70, 0.4),
                                         (90, 110, 0.8), (90, 72, 1.2), (90, 90, 1.6))),
    'head_dance': Motion('跳舞', '兴奋', ((90, 90, 0.0), (78, 70, 0.45),
                                         (104, 110, 0.9), (82, 75, 1.35),
                                         (100, 105, 1.8), (90, 90, 2.3))),
    'excited': Motion('兴奋表情', '兴奋', ((90, 90, 0.0), (82, 90, 0.45),
                                          (90, 90, 0.9))),
    'normal': Motion('正常表情', '正常', ((90, 90, 0.0), (90, 90, 0.5))),
    'sleep': Motion('睡觉表情', '睡觉', ((90, 90, 0.0), (108, 90, 1.0))),
    'wake_up': Motion('苏醒表情', '苏醒', ((108, 90, 0.0), (90, 90, 1.0))),
    'head_forward': Motion('看向正前方', '正常', ((90, 90, 0.0), (90, 90, 0.5))),
    'head_down': Motion('低头', '正常', ((90, 90, 0.0), (112, 90, 0.7))),
    'head_up': Motion('仰头', '正常', ((90, 90, 0.0), (68, 90, 0.7))),
    'head_left': Motion('向左看', '正常', ((90, 90, 0.0), (90, 115, 0.7))),
    'head_right': Motion('向右看', '正常', ((90, 90, 0.0), (90, 65, 0.7))),
    'head_reset': Motion('头部回中', '正常', ((90, 90, 0.0), (90, 90, 0.5))),
    'head_think': Motion('思考', '正常', ((90, 90, 0.0), (99, 104, 0.45),
                                         (96, 100, 1.1), (90, 90, 1.8))),
    'head_confused': Motion('困惑', '正常', ((90, 90, 0.0), (82, 102, 0.4),
                                            (96, 84, 0.8), (90, 90, 1.4))),
    'head_surprised': Motion('惊讶', '兴奋', ((90, 90, 0.0), (70, 90, 0.25),
                                             (76, 90, 0.85), (90, 90, 1.2))),
    'head_look_around': Motion('环视', '正常', ((90, 90, 0.0), (90, 65, 0.5),
                                               (90, 115, 1.0), (90, 70, 1.5),
                                               (90, 110, 2.0), (90, 90, 2.8))),
    'head_greet': Motion('打招呼', '兴奋', ((90, 90, 0.0), (80, 90, 0.35),
                                           (100, 90, 0.7), (90, 90, 1.25))),
    'head_goodbye': Motion('告别', '微笑', ((90, 90, 0.0), (90, 105, 0.45),
                                           (90, 75, 0.9), (90, 90, 1.5))),
    'head_refuse': Motion('拒绝', '正常', ((90, 90, 0.0), (90, 70, 0.35),
                                           (90, 110, 0.7), (90, 90, 1.0))),
    'head_breathing': Motion('呼吸', '正常', ((90, 90, 0.0), (86, 90, 0.5),
                                             (94, 90, 1.0), (86, 90, 1.5),
                                             (90, 90, 2.0))),
    'head_attention': Motion('注意力', '正常', ((90, 90, 0.0), (90, 90, 0.7))),
    'head_emotional': Motion('情感表达', '微笑', ((90, 90, 0.0), (86, 94, 0.5),
                                                 (90, 90, 1.0))),
    'head_listen': Motion('专注倾听', '正常', ((90, 90, 0.0), (96, 94, 0.4),
                                             (90, 90, 1.1))),
    'head_interest': Motion('表示兴趣', '微笑', ((90, 90, 0.0), (82, 98, 0.4),
                                                (90, 90, 1.0))),
    'head_concern': Motion('表示关心', '正常', ((90, 90, 0.0), (98, 84, 0.4),
                                               (90, 90, 1.1))),
    'head_agree': Motion('表示同意', '兴奋', ((90, 90, 0.0), (103, 90, 0.35),
                                             (82, 90, 0.7), (90, 90, 1.05))),
    'head_disagree': Motion('表示不同意', '正常', ((90, 90, 0.0), (90, 75, 0.35),
                                                  (90, 105, 0.7), (90, 90, 1.05))),
}

MODEL_FUNCTIONS = frozenset(MOTION_CATALOG)


def motion_duration(motion):
    return float(MOTION_CATALOG[motion].waypoints[-1][2])


def pose_at(motion, elapsed_seconds):
    """Linearly interpolate a named motion, clamped to its fixed duration."""
    waypoints = MOTION_CATALOG[motion].waypoints
    elapsed = max(0.0, min(float(elapsed_seconds), waypoints[-1][2]))
    for left, right in zip(waypoints, waypoints[1:]):
        if elapsed <= right[2]:
            span = right[2] - left[2]
            ratio = 0.0 if span <= 0 else (elapsed - left[2]) / span
            pitch = left[0] + (right[0] - left[0]) * ratio
            yaw = left[1] + (right[1] - left[1]) * ratio
            return pitch, yaw
    return float(waypoints[-1][0]), float(waypoints[-1][1])


def catalog_payload():
    """Return JSON-ready metadata for the browser without exposing waypoints."""
    return [
        {
            'name': name,
            'label': spec.label,
            'expression': spec.expression,
            'duration_sec': motion_duration(name),
            'simulated': True,
        }
        for name, spec in MOTION_CATALOG.items()
    ]
