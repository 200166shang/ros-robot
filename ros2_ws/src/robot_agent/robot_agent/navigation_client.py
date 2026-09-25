"""Narrow HTTP client for the isolated Mac-hosted Nav2 simulation."""

from __future__ import annotations

import ipaddress
import json
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID


DEFAULT_NAV2_ENDPOINT = "http://127.0.0.1:18092"
ALLOWED_LOCATION_IDS = frozenset({"goal_a", "goal_b"})
NAVIGATION_COMMAND_TO_LOCATION = {
    "navigate_to_goal_a": "goal_a",
    "navigate_to_goal_b": "goal_b",
}
NAVIGATION_MODEL_FUNCTIONS = {
    "navigate_to_goal_a": "navigate_to_goal_a",
    "navigate_to_goal_b": "navigate_to_goal_b",
    "cancel_navigation": "cancel_navigation",
    "navigation_status": "navigation_status",
}
NAVIGATION_TERMINAL_STATUSES = frozenset({"succeeded", "failed", "canceled"})
_KNOWN_TASK_STATUSES = NAVIGATION_TERMINAL_STATUSES | frozenset(
    {"submitting", "accepted", "running", "canceling"}
)
_MAX_RESPONSE_BYTES = 8192


class NavigationClientError(RuntimeError):
    """A safe, user-presentable failure talking to the local Nav2 gateway."""


class NavigationHttpClient:
    """Call a loopback-only HTTP API using fixed destination IDs, never poses."""

    def __init__(self, endpoint: str, timeout_seconds: float = 2.0) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Nav2 endpoint must be a plain loopback HTTP origin")

        try:
            is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            is_loopback = parsed.hostname.lower() == "localhost"
        if not is_loopback:
            raise ValueError("Nav2 endpoint must resolve to a loopback address")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero")

        self._base_url = "http://{}".format(parsed.netloc)
        self._timeout_seconds = float(timeout_seconds)
        self._opener = build_opener(ProxyHandler({}))

    def start_navigation(self, location_id: str) -> dict:
        """Submit a goal from the small fixed list approved by the project."""
        if not isinstance(location_id, str) or location_id not in ALLOWED_LOCATION_IDS:
            raise NavigationClientError("destination is not allowlisted")
        payload = self._request(
            "/api/v1/navigation/tasks",
            method="POST",
            body={"location_id": location_id},
            expected_status=202,
        )
        if (
            payload.get("location_id") != location_id
            or payload.get("status") not in {"submitting", "accepted", "running"}
        ):
            raise NavigationClientError("Nav2 returned an invalid task submission")
        self._validate_task_id(payload.get("task_id"))
        return payload

    def get_task(self, task_id: str) -> dict:
        """Read one previously submitted task and validate its response shape."""
        task_id = self._validate_task_id(task_id)
        payload = self._request(
            "/api/v1/navigation/tasks/{}".format(task_id),
            method="GET",
            expected_status=200,
        )
        if (
            payload.get("task_id") != task_id
            or payload.get("location_id") not in ALLOWED_LOCATION_IDS
            or payload.get("status") not in _KNOWN_TASK_STATUSES
        ):
            raise NavigationClientError("Nav2 returned an invalid task status")
        return payload

    def cancel_navigation(self, task_id: str) -> dict:
        """Request cancellation of a known task; completion remains asynchronous."""
        task_id = self._validate_task_id(task_id)
        payload = self._request(
            "/api/v1/navigation/tasks/{}/cancel".format(task_id),
            method="POST",
            body={},
            expected_status=202,
        )
        if (
            payload.get("task_id") != task_id
            or payload.get("status") != "canceling"
        ):
            raise NavigationClientError("Nav2 returned an invalid cancellation status")
        return payload

    @staticmethod
    def _validate_task_id(task_id: object) -> str:
        if not isinstance(task_id, str):
            raise NavigationClientError("task ID must be text")
        try:
            parsed_id = UUID(task_id)
        except (TypeError, ValueError, AttributeError) as error:
            raise NavigationClientError("task ID is invalid") from error
        return str(parsed_id)

    def _request(
        self,
        path: str,
        *,
        method: str,
        expected_status: int,
        body: Optional[dict] = None,
    ) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            self._base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status_code = response.status
                response_body = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            response_body = error.read(_MAX_RESPONSE_BYTES + 1)
            try:
                details = json.loads(response_body.decode("utf-8"))
                reason = details.get("error") if isinstance(details, dict) else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                reason = None
            message = "Nav2 API returned HTTP {}".format(error.code)
            if isinstance(reason, str) and reason:
                message += ": " + reason[:160]
            raise NavigationClientError(message) from error
        except (URLError, OSError, TimeoutError) as error:
            raise NavigationClientError(
                "Nav2 gateway is unavailable ({})".format(type(error).__name__)
            ) from error

        if status_code != expected_status:
            raise NavigationClientError(
                "Nav2 API returned unexpected HTTP {}".format(status_code)
            )
        if len(response_body) > _MAX_RESPONSE_BYTES:
            raise NavigationClientError("Nav2 response exceeded the size limit")
        try:
            payload = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise NavigationClientError("Nav2 response was not valid JSON") from error
        if not isinstance(payload, dict):
            raise NavigationClientError("Nav2 response must be a JSON object")
        return payload
