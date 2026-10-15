"""动作输入模型是 Schema、默认值和类型校验的共同声明。"""

from dataclasses import dataclass
from typing import Callable, Literal, Optional, Type, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
)
from typing_extensions import Annotated


def _number(value):
    """保持原数值契约，仅接受 Python/JSON 的整数和浮点数。"""
    if type(value) not in (int, float):
        raise ValueError("数值必须为整数或浮点数")
    return value


# strict float 仍可接收 Decimal 等可转换对象，因此先限定原始类型。
FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Number = Annotated[Union[StrictInt, FiniteFloat], BeforeValidator(_number)]
# 约束放在数值分支，避免联合外层生成非标准 gt/ge/le。
POSITIVE_BOUNDS = Field(gt=0)
PITCH_BOUNDS = Field(ge=65, le=120)
YAW_BOUNDS = Field(ge=50, le=130)
STEP_BOUNDS = Field(ge=0)
PositiveNumber = Annotated[
    Union[
        Annotated[StrictInt, POSITIVE_BOUNDS],
        Annotated[FiniteFloat, POSITIVE_BOUNDS],
    ],
    BeforeValidator(_number),
]
PitchNumber = Annotated[
    Union[
        Annotated[StrictInt, PITCH_BOUNDS],
        Annotated[FiniteFloat, PITCH_BOUNDS],
    ],
    BeforeValidator(_number),
]
YawNumber = Annotated[
    Union[
        Annotated[StrictInt, YAW_BOUNDS], Annotated[FiniteFloat, YAW_BOUNDS]
    ],
    BeforeValidator(_number),
]
StepNumber = Annotated[
    Union[
        Annotated[StrictInt, STEP_BOUNDS], Annotated[FiniteFloat, STEP_BOUNDS]
    ],
    BeforeValidator(_number),
]
Text = Annotated[str, Field(min_length=1, max_length=2048, pattern=r"\S")]


class ActionInput(BaseModel):
    """外部工具参数严格校验，未知字段不能成为内部执行参数。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class NoArguments(ActionInput):
    """无模型参数的动作。"""


class PositionInput(ActionInput):
    """头部角度范围；至少一轴由业务校验器确认。"""

    pitch: Optional[PitchNumber] = None
    yaw: Optional[YawNumber] = None


class DurationInput(ActionInput):
    """动作持续时间使用正有限秒数。"""

    duration: PositiveNumber


class BreathingInput(ActionInput):
    """呼吸周期限制资源，保留既有默认值。"""

    cycles: Annotated[StrictInt, Field(ge=1, le=64)] = 5
    duration: PositiveNumber = 0.5


class AttentionInput(ActionInput):
    """注意方向与时间。"""

    direction: Literal["left", "right", "up", "down", "center"] = "center"
    duration: PositiveNumber = 1.0


class EmotionalInput(ActionInput):
    """情感类别与时间。"""

    emotion: Literal["happy", "sad", "angry", "excited", "calm"] = "happy"
    duration: PositiveNumber = 3.0


class LocationInput(ActionInput):
    """导航目标名称。"""

    location: Text


class PoseInput(ActionInput):
    """地图位置与四元数，单位姿态由业务校验器确认。"""

    name: Text
    x: Number
    y: Number
    z: Number = 0.0
    qx: Number = 0.0
    qy: Number = 0.0
    qz: Number = 0.0
    qw: Number = 1.0


class SongInput(ActionInput):
    """歌曲与队列接受非空名称。"""

    song_name: Text


class RecommendationInput(ActionInput):
    """省略歌曲时按当前曲目推荐。"""

    song_name: Optional[Text] = None


class StepInput(ActionInput):
    """非负音量步长，执行时按原契约饱和。"""

    step: StepNumber = 5


class LevelInput(ActionInput):
    """音量执行时量化并按原契约饱和。"""

    level: Number = 50


@dataclass(frozen=True)
class ActionHandler:
    """输入模型、业务校验和实现；仅等待设备的实现接收显式期限。"""

    execute: Callable
    validate: Optional[Callable[..., None]] = None
    inputs: Type[ActionInput] = NoArguments
    timed: bool = False
