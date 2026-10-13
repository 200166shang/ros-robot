"""Online Agent interaction Interface, independent of ROS and provider SDKs."""

from __future__ import annotations

import ast
import csv
import io
import json
import logging
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Protocol, Tuple, TypedDict, Union, cast

LOGGER = logging.getLogger(__name__)
Argument = Union[str, int, float]


class DeviceResult(TypedDict, total=False):
    """设备确认：success 为必需字段，其余字段依执行结果提供。"""

    success: bool
    simulated: bool
    result: Dict[str, Union[str, float, bool, None]]
    error: str


class ActionResult(DeviceResult, total=False):
    """动作事件额外包含原始调用字符串 call。"""

    call: str


class TurnResult(TypedDict, total=False):
    """一轮交互的 JSON 契约；失败可通过 error 补充原因。"""

    success: bool
    response: str
    actions: List[ActionResult]
    error: str


class Provider(Protocol):
    """真实在线与固定响应 provider 共用的 Seam。"""

    def complete(self, text: str) -> str:
        """返回待校验的 function/response 文本，失败时抛出异常。"""
        ...


class Devices(Protocol):
    """设备与测试 Adapter 共用的 Seam。"""

    def execute(self, name: str, args: List[Argument]) -> DeviceResult:
        """执行动作并返回确认；未知动作返回 success=false。"""
        ...


class OnlineAgent:
    """串行处理文本轮次，返回回复和确认的动作结果。"""

    def __init__(self, provider: Provider, devices: Devices) -> None:
        self._provider = provider
        self._devices = devices
        self._turn_lock = threading.Lock()

    def submit(self, text: str) -> TurnResult:
        """提交文本；输入、网络和动作失败转换为可观察结果，不泄露外部错误详情。"""
        with self._turn_lock:
            if not isinstance(text, str) or not text.strip():
                return {"success": False, "response": "请输入文本。", "actions": [], "error": "empty_input"}

            # 外部 Adapter 可能抛出第三方异常；在这里转换为失败结果并保留安全的日志上下文。
            try:
                raw_output = self._provider.complete(text)
            except Exception as error:
                LOGGER.warning("Online Agent provider request failed (%s)", type(error).__name__)
                return {"success": False, "response": "在线模型请求失败，请稍后重试。", "actions": [], "error": "provider_failed"}

            try:
                calls, model_response = _parse_model_output(raw_output)
            except (ValueError, TypeError):
                return {"success": False, "response": "在线模型输出无效，未执行动作。", "actions": [], "error": "invalid_output"}

            # 源行为按原始调用字符串同轮去重，跨轮清空；不同动作并发。
            unique_calls = list(dict.fromkeys(calls))
            with ThreadPoolExecutor(max_workers=8) as pool:
                actions = list(pool.map(self._execute, unique_calls))
            return _summarize_turn(model_response, actions)

    def _execute(self, call: str) -> ActionResult:
        try:
            name, args = _parse_call(call)
        except (ValueError, TypeError, csv.Error):
            return {"call": call, "success": False, "simulated": False, "error": "action_failed"}

        # 设备 Adapter 的失败不能中断其他动作，且异常字符串可能含敏感配置。
        try:
            result = self._devices.execute(name, args)
        except Exception as error:
            LOGGER.warning("Online Agent device action failed (%s)", type(error).__name__)
            return {"call": call, "success": False, "simulated": False, "error": "action_failed"}

        if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
            return {"call": call, "success": False, "simulated": False, "error": "action_failed"}
        return cast(ActionResult, dict(result, call=call))


class SimulatedDevices:
    """Explicit simulation Adapter; unsupported actions fail closed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._volume = 50.0
        self._muted = False
        self._song: Optional[str] = None
        self._expression = "正常"
        self._head = "center"

    def execute(self, name: str, args: List[Argument]) -> DeviceResult:
        """执行模拟动作，返回确认结果；无效参数抛出 ValueError。"""
        result: Dict[str, Union[str, float, bool, None]]
        with self._lock:
            if name in {"volume_set", "volume_up", "volume_down"}:
                if len(args) > 1:
                    raise ValueError("too many arguments")
                default_value = 50 if name == "volume_set" else 5
                value = float(args[0]) if args else default_value
                if not math.isfinite(value):
                    raise ValueError("invalid volume")
                if name == "volume_set":
                    target_volume = value
                else:
                    direction = 1 if name == "volume_up" else -1
                    target_volume = self._volume + value * direction
                self._volume = max(0, min(100, target_volume))
                result = {"volume": self._volume}
            elif name in {"volume_mute", "volume_unmute", "volume_status"}:
                if args:
                    raise ValueError("unexpected arguments")
                if name != "volume_status":
                    self._muted = name == "volume_mute"
                result = {"volume": self._volume, "muted": self._muted}
            elif name in {"play_music", "play_song"}:
                if len(args) != 1 or not isinstance(args[0], str) or not args[0].strip():
                    raise ValueError("song required")
                self._song = args[0]
                result = {"song": self._song}
            elif name in {"stop_music", "music_status"}:
                if args:
                    raise ValueError("unexpected arguments")
                if name == "stop_music":
                    self._song = None
                result = {"song": self._song, "is_playing": self._song is not None}
            elif name in {
                "head_forward",
                "head_left",
                "head_right",
                "head_up",
                "head_down",
                "head_reset",
            }:
                if args:
                    raise ValueError("unexpected arguments")
                self._head = name[5:]
                result = {"head": self._head}
            elif name in {
                "head_smile",
                "head_nod",
                "head_dance",
                "excited",
                "head_shake",
                "normal",
                "sleep",
                "wake_up",
            }:
                if args:
                    raise ValueError("unexpected arguments")
                self._expression = {
                    "head_smile": "兴奋",
                    "head_nod": "兴奋",
                    "head_dance": "兴奋",
                    "excited": "兴奋",
                    "head_shake": "正常",
                    "normal": "正常",
                    "sleep": "good_night",
                    "wake_up": "苏醒",
                }[name]
                result = {"expression": self._expression}
            else:
                return {
                    "success": False,
                    "simulated": False,
                    "error": "not_implemented",
                }
            return {"success": True, "simulated": True, "result": result}


def _parse_call(call: str) -> Tuple[str, List[Argument]]:
    match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)(?:\((.*)\))?", call.strip())
    if not match:
        raise ValueError("invalid call")
    name, arguments = match.groups()
    if not arguments:
        return name, []
    # 兼容旧调用中的无引号字符串，同时按字面值解析混合参数，绝不执行模型表达式。
    try:
        args = ast.literal_eval("[" + arguments + "]")
    except (ValueError, SyntaxError):
        args = next(csv.reader(io.StringIO(arguments), skipinitialspace=True))
    if any(not isinstance(arg, (str, int, float)) or isinstance(arg, bool) for arg in args):
        raise ValueError("invalid argument")
    return name, args


def _parse_model_output(raw: str) -> Tuple[List[str], str]:
    """校验完整的旧在线协议；任何无效输出均在动作执行前拒绝。"""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 65536:
        raise ValueError("output too large")
    payload = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"function", "response"}:
        raise ValueError("invalid protocol fields")
    calls = payload["function"]
    response = payload["response"]
    if not isinstance(calls, list) or len(calls) > 32 or any(not isinstance(call, str) for call in calls):
        raise ValueError("invalid function list")
    if not isinstance(response, str):
        raise ValueError("invalid response")
    return calls, response


def _summarize_turn(model_response: str, actions: List[ActionResult]) -> TurnResult:
    """根据确认结果汇总回复；动作失败时替换模型可能伪报成功的文本。"""
    success = all(action["success"] for action in actions)
    response = model_response if success else "请求中的动作未全部完成，请查看动作结果。"
    action_messages = []
    for action in actions:
        confirmed_simulation = action["success"] and action.get("simulated", False)
        prefix = "模拟动作已完成：" if confirmed_simulation else "动作失败："
        action_messages.append(prefix + action["call"])
    if action_messages:
        response += "\n" + "\n".join(action_messages)
    return {"success": success, "response": response, "actions": actions}


def _unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result
