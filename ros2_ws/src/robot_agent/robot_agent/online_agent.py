"""Online Agent interaction Interface, independent of ROS and provider SDKs."""

import ast
import csv
import io
import math
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

import json
import threading


class SimulatedDevices:
    """Explicit simulation Adapter; unsupported actions fail closed."""

    def __init__(self):
        self._lock = threading.Lock()
        self._volume = 50.0
        self._muted = False
        self._song: Optional[str] = None
        self._expression = "正常"
        self._head = "center"

    def execute(self, name, args):
        result: Dict[str, Any]
        with self._lock:
            if name in {"volume_set", "volume_up", "volume_down"}:
                if len(args) > 1:
                    raise ValueError("too many arguments")
                value = float(args[0]) if args else (50 if name == "volume_set" else 5)
                if not math.isfinite(value):
                    raise ValueError("invalid volume")
                self._volume = max(
                    0,
                    min(
                        100,
                        (
                            value
                            if name == "volume_set"
                            else self._volume
                            + value * (1 if name == "volume_up" else -1)
                        ),
                    ),
                )
                result = {"volume": self._volume}
            elif name in {"volume_mute", "volume_unmute", "volume_status"}:
                if args:
                    raise ValueError("unexpected arguments")
                if name != "volume_status":
                    self._muted = name == "volume_mute"
                result = {"volume": self._volume, "muted": self._muted}
            elif name in {"play_music", "play_song"}:
                if (
                    len(args) != 1
                    or not isinstance(args[0], str)
                    or not args[0].strip()
                ):
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


def _parse_call(call):
    match = re.fullmatch(r"([A-Za-z_][A-Za-z_0-9]*)(?:\((.*)\))?", call.strip())
    if not match:
        raise ValueError("invalid call")
    name, arguments = match.groups()
    if not arguments:
        return name, []
    # Legacy accepts unquoted strings and converts numeric values in device code.
    # Literal parsing handles mixed quoted strings/numbers without evaluating code.
    try:
        args = ast.literal_eval("[" + arguments + "]")
    except (ValueError, SyntaxError):
        args = next(csv.reader(io.StringIO(arguments), skipinitialspace=True))
    if any(
        not isinstance(arg, (str, int, float)) or isinstance(arg, bool) for arg in args
    ):
        raise ValueError("invalid argument")
    return name, args


class OnlineAgent:
    """Submit text and observe a reply plus confirmed action results."""

    def __init__(self, provider, devices):
        self._provider = provider
        self._devices = devices
        self._turn_lock = threading.Lock()

    def submit(self, text):
        with self._turn_lock:
            if not isinstance(text, str) or not text.strip():
                return {
                    "success": False,
                    "response": "请输入文本。",
                    "actions": [],
                    "error": "empty_input",
                }
            try:
                raw = self._provider.complete(text)
            except Exception:
                # Provider exceptions may contain URLs, input or credentials.
                return {
                    "success": False,
                    "response": "在线模型请求失败，请稍后重试。",
                    "actions": [],
                    "error": "provider_failed",
                }
            try:
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > 65536:
                    raise ValueError("output too large")
                payload = json.loads(raw, object_pairs_hook=_unique_object)
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"function", "response"}
                    or not isinstance(payload["function"], list)
                    or len(payload["function"]) > 32
                    or any(not isinstance(call, str) for call in payload["function"])
                    or not isinstance(payload["response"], str)
                ):
                    raise ValueError("invalid protocol")
            except (ValueError, TypeError):
                return {
                    "success": False,
                    "response": "在线模型输出无效，未执行动作。",
                    "actions": [],
                    "error": "invalid_output",
                }
            # Preserve source deduplication by exact call string, scoped to this turn.
            calls = list(dict.fromkeys(payload["function"]))
            with ThreadPoolExecutor(max_workers=8) as pool:
                actions = list(pool.map(self._execute, calls))
            success = all(action["success"] for action in actions)
            response = (
                payload["response"]
                if success
                else "请求中的动作未全部完成，请查看动作结果。"
            )
            if actions:
                # A model's claim is not confirmation; append actual device outcomes.
                response += "\n" + "\n".join(
                    (
                        "模拟动作已完成："
                        if action["success"] and action.get("simulated", False)
                        else "动作失败："
                    )
                    + action["call"]
                    for action in actions
                )
            return {"success": success, "response": response, "actions": actions}

    def _execute(self, call):
        try:
            name, args = _parse_call(call)
            result = self._devices.execute(name, args)
            if not isinstance(result, dict) or not isinstance(
                result.get("success"), bool
            ):
                raise ValueError("invalid device result")
            return dict(result, call=call)
        except Exception:
            return {
                "call": call,
                "success": False,
                "simulated": False,
                "error": "action_failed",
            }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result
