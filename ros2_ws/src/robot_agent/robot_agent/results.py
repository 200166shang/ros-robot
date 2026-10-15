"""模型、动作、文本与语音的不可变记录及出口 JSON 转换。"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple, Union


def _freeze(value: Any) -> Any:
    """递归复制并冻结 JSON 数据，避免设备和调用者改写既有快照。"""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _json_value(value: Any) -> Any:
    """仅在外部出口恢复 JSON 对象与数组。"""
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class ToolCall:
    """已收齐的原生工具请求，参数仍需动作目录校验。"""

    call_id: str
    name: str
    arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        """模型传输结束时取得请求快照。"""
        object.__setattr__(self, "arguments", _freeze(self.arguments))


@dataclass(frozen=True)
class ModelReply:
    """完整聊天文字及至多一个原生完整计划请求。"""

    response: str = ""
    tool_call: Optional[ToolCall] = None


@dataclass(frozen=True)
class ActionReceipt:
    """设备回执，不携带模型或语音状态。"""

    status: str
    detail: str = ""
    data: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        """接收回执时立刻取得嵌套快照。"""
        object.__setattr__(self, "data", _freeze(self.data))


@dataclass(frozen=True)
class ActionOutcome:
    """计划中一项动作的参数与当前事实，包括未执行余项。"""

    name: str
    parameters: Mapping[str, Any]
    status: str = "not_executed"
    detail: Optional[str] = None
    data: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        """结果同时拥有参数和设备数据的独立快照。"""
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(self, "data", _freeze(self.data))


@dataclass(frozen=True)
class ExecutionResult:
    """全计划执行快照，核对只生成新记录。"""

    turn_id: str
    status: str
    reply: str
    actions: Tuple[ActionOutcome, ...]
    tool_call_id: Optional[str] = None

    def __post_init__(self) -> None:
        """脱离执行器用于推进状态的列表。"""
        object.__setattr__(self, "actions", tuple(self.actions))


@dataclass(frozen=True)
class TurnResult:
    """一轮文本交互的模型回复、动作事实与独立记忆告警。"""

    turn_id: str
    status: str
    reply: str
    execution: Optional[ExecutionResult] = None
    memory_warnings: Optional[Tuple[str, ...]] = None

    def __post_init__(self) -> None:
        """告警同样不能由记忆实现的列表修改。"""
        if self.memory_warnings is not None:
            object.__setattr__(
                self, "memory_warnings", tuple(self.memory_warnings)
            )

    @property
    def actions(self) -> Tuple[ActionOutcome, ...]:
        """直接读取完整动作快照，聊天回合为空。"""
        return self.execution.actions if self.execution is not None else ()

    @classmethod
    def from_execution(cls, result: ExecutionResult) -> "TurnResult":
        """组合执行事实，不复制或修改动作状态。"""
        return cls(result.turn_id, result.status, result.reply, result)


def make_result(turn_id: str, status: str, reply: str) -> TurnResult:
    """建立无动作的文本结果。"""
    return TurnResult(turn_id, status, reply)


@dataclass(frozen=True)
class VoiceRecord:
    """组合文本回合与识别、会话、语音输出及保存事实。"""

    turn: TurnResult
    transcript: Optional[str] = None
    session_state: Optional[str] = None
    input_status: Optional[str] = None
    asr_status: Optional[str] = None
    tts_status: Optional[str] = None
    playback_status: Optional[str] = None
    audio_path: Optional[str] = None
    record_status: Optional[str] = None

    @property
    def turn_id(self) -> str:
        """语音产物始终关联原文本回合。"""
        return self.turn.turn_id

    @property
    def status(self) -> str:
        """输出失败不改变文本回合状态。"""
        return self.turn.status

    @property
    def reply(self) -> str:
        """输出只消费已确定的文本回复。"""
        return self.turn.reply

    @property
    def actions(self) -> Tuple[ActionOutcome, ...]:
        """返回原回合的动作事实。"""
        return self.turn.actions


def result_to_json(result: Union[TurnResult, VoiceRecord]) -> Dict[str, Any]:
    """在保存、发布与命令行出口生成兼容的平铺 JSON 字段。"""
    turn = result.turn if isinstance(result, VoiceRecord) else result
    payload: Dict[str, Any] = {
        "turn_id": turn.turn_id,
        "status": turn.status,
        "reply": turn.reply,
        "actions": [],
    }
    for action in turn.actions:
        item = {
            "name": action.name,
            "parameters": _json_value(action.parameters),
            "status": action.status,
        }
        if action.detail is not None:
            item["detail"] = action.detail
        if action.data is not None:
            item["data"] = _json_value(action.data)
        payload["actions"].append(item)
    if turn.memory_warnings is not None:
        payload["memory_warnings"] = list(turn.memory_warnings)
    if isinstance(result, VoiceRecord):
        for name in (
            "transcript",
            "session_state",
            "input_status",
            "asr_status",
            "tts_status",
            "playback_status",
            "audio_path",
            "record_status",
        ):
            value = getattr(result, name)
            if value is not None:
                payload[name] = value
    return payload
