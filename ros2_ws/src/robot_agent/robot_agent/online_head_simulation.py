"""头部和 LCD 的可观察模拟；源动作序列使用虚拟时间，不创建驱动。"""

from functools import partial
from typing import Callable, Dict, Optional, Sequence, Tuple

from .online_action_contracts import ActionHandler
from .online_simulation import simulated, validate_number

# 旧注册函数仅改变 LCD，不能把这些表情宣称为真实舵机点头或跳舞。
EXPRESSIONS = {
    "head_smile": "兴奋",
    "head_nod": "兴奋",
    "head_shake": "正常",
    "head_dance": "兴奋",
    "excited": "兴奋",
    "normal": "正常",
    "sleep": "good_night",
    "wake_up": "苏醒",
}
BASIC_POSES = {
    "head_forward": (90, 90),
    "head_reset": (90, 90),
    "head_down": (65, None),
    "head_up": (120, None),
    "head_left": (None, 130),
    "head_right": (None, 50),
}
# 元组为 pitch/yaw；None 保留当前轴。
# 以源姿态顺序为准，duration 均分虚拟时间。
GESTURES = {
    "head_think": (
        2.0,
        [(80, 90), (82, 75), (90, 90), (85, 105), (100, 90), (90, 90)],
    ),
    "head_confused": (1.5, [(None, 80), (None, 100), (None, 90)]),
    "head_surprised": (1.0, [(105, None), (85, None), (90, None)]),
    "head_look_around": (
        3.0,
        [
            (100, 90),
            (105, 65),
            (80, 60),
            (90, 90),
            (105, 115),
            (80, 120),
            (110, 90),
            (75, 90),
            (90, 90),
        ],
    ),
    "head_greet": (
        2.0,
        [
            (100, 90),
            (82, 90),
            (95, 90),
            (90, 75),
            (90, 105),
            (90, 90),
            (80, 90),
            (90, 90),
        ],
    ),
    "head_goodbye": (1.5, [(65, None), (90, 90), (85, None), (90, None)]),
    "head_refuse": (
        1.0,
        [(None, 130), (None, 50)] * 2 + [(90, 90), (85, None), (90, None)],
    ),
    "head_listen": (
        2.0,
        [
            (82, 90),
            (85, 75),
            (85, 105),
            (82, 90),
            (78, 90),
            (82, 90),
            (90, 90),
        ],
    ),
    "head_interest": (
        1.5,
        [(100, 90), (85, 90), (88, 75), (88, 105), (100, 90), (90, 90)],
    ),
    "head_concern": (
        2.0,
        [
            (80, 90),
            (82, 75),
            (82, 105),
            (80, 90),
            (75, 90),
            (80, 90),
            (90, 90),
        ],
    ),
    "head_agree": (
        1.0,
        [(82, 90), (95, 90), (80, 90), (90, 90), (100, 90), (90, 90)],
    ),
    "head_disagree": (
        1.0,
        [(90, 75), (90, 105), (90, 70), (90, 110), (90, 90)],
    ),
}
Pose = Tuple[Optional[float], Optional[float]]


def validate_position(
    pitch: Optional[float] = None,
    yaw: Optional[float] = None,
) -> None:
    """位置至少指定一个轴，并遵循源舵机角度范围。"""
    if pitch is None and yaw is None:
        raise ValueError("必须指定 pitch 或 yaw")
    for value, field, lower, upper in (
        (pitch, "pitch", 65, 120),
        (yaw, "yaw", 50, 130),
    ):
        if value is not None:
            validate_number(value, field)
            if not lower <= value <= upper:
                raise ValueError(field + " 超出头部角度范围")


def validate_duration(duration: float) -> None:
    """动作时间必须是正有限秒数；模拟使用虚拟时间而不等待。"""
    validate_number(duration, "duration")
    if duration <= 0:
        raise ValueError("duration 必须大于零")


def validate_breathing(cycles: int = 5, duration: float = 0.5) -> None:
    """呼吸次数使用正整数，虚拟轨迹最多64周期以限制输入资源。"""
    if type(cycles) is not int or not 1 <= cycles <= 64:
        raise ValueError("cycles 必须为1至64的整数")
    validate_duration(duration)


def validate_attention(
    direction: str = "center", duration: float = 1.0
) -> None:
    """注意方向只接受源五种方向，不静默替换未知方向。"""
    if direction not in ("left", "right", "up", "down", "center"):
        raise ValueError("未知注意方向")
    validate_duration(duration)


def validate_emotional(emotion: str = "happy", duration: float = 3.0) -> None:
    """情感只接受源五种类型。"""
    if emotion not in ("happy", "sad", "angry", "excited", "calm"):
        raise ValueError("未知情感")
    validate_duration(duration)


class HeadSimulation:
    """持有姿态、LCD 和本动作虚拟轨迹，不保留无限历史队列。"""

    def __init__(self) -> None:
        """初始化源中心姿态和正常表情。"""
        self.pitch = 90.0
        self.yaw = 90.0
        self.display = "正常"

    def expression(self, display: str) -> Dict:
        """更新 LCD 模拟状态，保留头部姿态。"""
        self.display = display
        return simulated("LCD " + display, **self._state())

    def head_position(
        self,
        pitch: Optional[float] = None,
        yaw: Optional[float] = None,
    ) -> Dict:
        """更新指定轴，未指定轴保留当前角度。"""
        return self._perform([(pitch, yaw)], 0.0)

    def gesture_handler(self, name: str, default: float) -> Callable:
        """相同参数契约的组合姿态共用实现，保留各动作默认时间。"""

        def execute(duration: float = default) -> Dict:
            """完成一个组合动作的完整虚拟轨迹后返回快照。"""
            return self._perform(GESTURES[name][1], duration)

        return execute

    def head_breathing(self, cycles: int = 5, duration: float = 0.5) -> Dict:
        """按周期展开吸气和呼气，并回到中心俯仰角。"""
        poses = [(92, None), (88, None)] * cycles + [(90, None)]
        return self._perform(poses, cycles * duration)

    def head_attention(
        self,
        direction: str = "center",
        duration: float = 1.0,
    ) -> Dict:
        """转向注意方向后回到中心，全部步骤均为模拟。"""
        poses = {
            "left": (None, 130),
            "right": (None, 50),
            "up": (120, None),
            "down": (65, None),
            "center": (90, 90),
        }
        return self._perform([poses[direction], (90, 90)], duration)

    def head_emotional(
        self,
        emotion: str = "happy",
        duration: float = 3.0,
    ) -> Dict:
        """按源情感组合展开姿态，按序执行而非创建子动作线程。"""
        nod = [(65, None), (90, 90)]
        shake = [(None, 130), (None, 50), (90, 90)]
        poses = {
            "happy": nod * 2 + [(None, 85), (None, 95), (None, 90)],
            "sad": [(85, None)] + shake + [(90, None)],
            "angry": GESTURES["head_confused"][1] + [(95, None), (90, None)],
            "excited": nod * 3 + GESTURES["head_look_around"][1],
            "calm": [(92, None), (88, None)] * 3 + [(90, None)],
        }
        return self._perform(poses[emotion], duration)

    def _perform(self, poses: Sequence[Pose], duration: float) -> Dict:
        """按序更新姿态并返回有界轨迹；duration 不影响真实时间。"""
        # 1. 本动作独占轨迹，保留每步姿态与有意重复。
        steps = []
        for pitch, yaw in poses:
            if pitch is not None:
                self.pitch = pitch
            if yaw is not None:
                self.yaw = yaw
            steps.append(
                dict(
                    pitch=self.pitch,
                    yaw=self.yaw,
                    duration=duration / len(poses),
                )
            )

        # 2. 只有完整虚拟序列结束才返回模拟成功。
        return simulated(
            "头部姿态与轨迹", **self._state(), steps=steps, duration=duration
        )

    def _state(self) -> Dict:
        """返回当前姿态和 LCD 显示字段。"""
        return dict(pitch=self.pitch, yaw=self.yaw, display=self.display)


def head_actions(head: HeadSimulation) -> Dict[str, ActionHandler]:
    """头部能力返回完整动作表，不依赖或修改动作注册表。"""
    # 1. 无参数LCD和基础姿态使用已绑定的执行函数。
    handlers = {
        name: ActionHandler(partial(head.expression, display))
        for name, display in EXPRESSIONS.items()
    }
    handlers.update(
        {
            name: ActionHandler(partial(head._perform, [(pitch, yaw)], 0.0))
            for name, (pitch, yaw) in BASIC_POSES.items()
        }
    )

    # 2. 组合动作在同一能力表中绑定执行与校验契约。
    handlers.update(
        {
            name: ActionHandler(
                head.gesture_handler(name, default), validate_duration
            )
            for name, (default, _) in GESTURES.items()
        }
    )
    handlers.update(
        {
            "head_position": ActionHandler(
                head.head_position, validate_position
            ),
            "head_breathing": ActionHandler(
                head.head_breathing, validate_breathing
            ),
            "head_attention": ActionHandler(
                head.head_attention, validate_attention
            ),
            "head_emotional": ActionHandler(
                head.head_emotional, validate_emotional
            ),
        }
    )
    return handlers
