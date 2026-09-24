"""Pure, fail-closed decision boundary for Qwen ``res``/``fc`` output.

This module deliberately has no ROS imports and performs no I/O.  Callers must
provide any function-to-command mappings explicitly; the default allowlist is
empty so model-generated functions are denied until a mapping is deliberately
enabled by a future integration.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from robot_head.catalog import MODEL_FUNCTIONS


class DecisionKind(str, Enum):
    CHAT_ONLY = "chat_only"
    COMMAND = "command"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    model_response: str | None = None
    command: str | None = None
    reason: str | None = None


_ROS_COMMANDS = frozenset(
    {"status", "start_camera", "stop_camera", "start_tracking", "stop_tracking"}
) | MODEL_FUNCTIONS
_STATUS_QUERY_FUNCTIONS = ("query_camera_status", "query_person_tracking_status")
_DEFAULT_MAX_BYTES = 16 * 1024


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _rejected(reason: str) -> Decision:
    return Decision(kind=DecisionKind.REJECTED, reason=reason)


def decide_model_output(
    raw: str,
    function_allowlist: Mapping[object, str] | None = None,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> Decision:
    """Parse one complete Qwen response and return chat, one command, or deny.

    ``function_allowlist`` maps exact function strings (or the ordered status
    query pair) to canonical ROS commands. No mapping is enabled by default.
    Every other multi-function output is denied; this function never publishes.
    """
    if not isinstance(raw, str):
        return _rejected("input_not_string")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        return _rejected("invalid_size_limit")
    try:
        encoded = raw.encode("utf-8")
    except UnicodeEncodeError:
        return _rejected("input_not_valid_utf8")
    if len(encoded) > max_bytes:
        return _rejected("input_too_large")

    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, _DuplicateKeyError, TypeError, ValueError):
        return _rejected("invalid_json")

    if not isinstance(payload, dict) or set(payload) != {"res", "fc"}:
        return _rejected("invalid_object_fields")
    response = payload["res"]
    functions = payload["fc"]
    if not isinstance(response, str) or not isinstance(functions, list):
        return _rejected("invalid_field_types")
    if any(not isinstance(function, str) for function in functions):
        return _rejected("invalid_function_type")
    if not functions:
        return Decision(kind=DecisionKind.CHAT_ONLY, model_response=response)
    if len(functions) > 1 and tuple(functions) != _STATUS_QUERY_FUNCTIONS:
        return _rejected("multiple_functions_not_allowed")

    allowlist = {} if function_allowlist is None else function_allowlist
    if not isinstance(allowlist, Mapping):
        return _rejected("invalid_allowlist")
    for signature, command in allowlist.items():
        valid_signature = (
            (isinstance(signature, str) and bool(signature))
            or (isinstance(signature, tuple) and signature == _STATUS_QUERY_FUNCTIONS)
        )
        if not valid_signature or not isinstance(command, str) or command not in _ROS_COMMANDS:
            return _rejected("invalid_allowlist")

    signature = functions[0] if len(functions) == 1 else tuple(functions)
    command = allowlist.get(signature)
    if command is None:
        return _rejected("function_not_allowlisted")
    return Decision(
        kind=DecisionKind.COMMAND,
        model_response=response,
        command=command,
    )
