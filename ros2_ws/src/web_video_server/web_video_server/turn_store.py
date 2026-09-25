"""In-memory turn state with an optional privacy-preserving JSONL event log."""

from collections import OrderedDict
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid


_LOG_FIELDS = (
    "turn_id",
    "run_id",
    "stage",
    "status",
    "event_time_utc",
    "elapsed_ms",
    "error_code",
    "command",
    "audio_status",
)
_TERMINAL_STATUSES = frozenset(("succeeded", "failed", "rejected"))


class TurnInProgressError(RuntimeError):
    """Raised when a second UI request would overlap the current turn."""


class AudioResponseUnavailable(RuntimeError):
    """Raised when speech is requested before the text response is ready."""


def utc_now():
    """Return a timezone-aware ISO timestamp suitable for display and logs."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TurnEventStore:
    """Keep recent UI turns in RAM and write only non-content event metadata."""

    def __init__(self, run_log_dir=None, max_turns=100):
        self.run_id = uuid.uuid4().hex
        self._max_turns = max(1, int(max_turns))
        self._turns = OrderedDict()
        self._lock = threading.RLock()
        self._events_path = None

        if run_log_dir:
            run_dir = Path(run_log_dir).expanduser() / self.run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            manifest = {
                "schema_version": 1,
                "run_id": self.run_id,
                "started_at_utc": utc_now(),
                "content_logging": False,
            }
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self._events_path = run_dir / "events.jsonl"

    def create_turn(self, turn_id, user_text):
        """Create the UI-visible queued state; the text stays in memory only."""
        event = {
            "turn_id": turn_id,
            "run_id": self.run_id,
            "stage": "accepted",
            "status": "queued",
            "event_time_utc": utc_now(),
        }
        with self._lock:
            for current in self._turns.values():
                if not is_terminal_status(current["status"]):
                    raise TurnInProgressError(
                        "the previous interaction turn is still active"
                    )
            self._turns[turn_id] = {
                "turn_id": turn_id,
                "run_id": self.run_id,
                "user_text": user_text,
                "response_text": None,
                "audio_status": "not_requested",
                "audio_error_code": None,
                "audio_elapsed_ms": None,
                "stage": event["stage"],
                "status": event["status"],
                "error_code": None,
                "elapsed_ms": None,
                "updated_at_utc": event["event_time_utc"],
                "events": [dict(event)],
            }
            self._trim_turns()
            self._append_safe_log(event)
            return self._copy_turn(self._turns[turn_id])

    def ingest_event(self, event):
        """Merge one validated bridge event into a turn and persist safe fields."""
        if not isinstance(event, dict):
            raise ValueError("turn event must be an object")
        turn_id = event.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("turn event has no turn_id")

        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None or event.get("run_id") != self.run_id:
                return None

            safe_event = {
                "turn_id": turn_id,
                "run_id": self.run_id,
                "stage": str(event.get("stage", "unknown"))[:32],
                "status": str(event.get("status", "unknown"))[:32],
                "event_time_utc": str(event.get("event_time_utc") or utc_now())[:64],
            }
            if isinstance(event.get("elapsed_ms"), (int, float)):
                safe_event["elapsed_ms"] = max(0, int(event["elapsed_ms"]))
            if isinstance(event.get("error_code"), str):
                safe_event["error_code"] = event["error_code"][:64]
            if isinstance(event.get("command"), str):
                safe_event["command"] = event["command"][:64]

            if safe_event["stage"] == "audio":
                audio_status = event.get("audio_status", event.get("status"))
                if audio_status not in ("generating", "ready", "failed"):
                    raise ValueError("invalid audio status")
                safe_event["audio_status"] = audio_status
                turn["audio_status"] = audio_status
                turn["audio_error_code"] = safe_event.get("error_code")
                turn["audio_elapsed_ms"] = safe_event.get("elapsed_ms")
                turn["events"].append(safe_event)
                turn["events"] = turn["events"][-32:]
                self._turns.move_to_end(turn_id)
                self._append_safe_log(safe_event)
                return self._copy_turn(turn)

            turn["stage"] = safe_event["stage"]
            turn["status"] = safe_event["status"]
            turn["updated_at_utc"] = safe_event["event_time_utc"]
            turn["error_code"] = safe_event.get("error_code")
            turn["elapsed_ms"] = safe_event.get("elapsed_ms")
            response_text = event.get("response_text")
            if isinstance(response_text, str):
                turn["response_text"] = response_text[:12000]
            turn["events"].append(safe_event)
            turn["events"] = turn["events"][-32:]
            self._turns.move_to_end(turn_id)
            self._append_safe_log(safe_event)
            return self._copy_turn(turn)

    def request_audio(self, turn_id):
        """Mark one completed response for explicit browser-side speech output."""
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None:
                raise KeyError(turn_id)
            if not turn["response_text"] or not is_terminal_status(turn["status"]):
                raise AudioResponseUnavailable(
                    "the text response is not complete yet"
                )
            if turn["audio_status"] in ("queued", "generating", "ready"):
                return self._copy_turn(turn), False

            turn["audio_status"] = "queued"
            turn["audio_error_code"] = None
            event = {
                "turn_id": turn_id,
                "run_id": self.run_id,
                "stage": "audio",
                "status": "queued",
                "audio_status": "queued",
                "event_time_utc": utc_now(),
            }
            turn["events"].append(dict(event))
            turn["events"] = turn["events"][-32:]
            self._append_safe_log(event)
            return self._copy_turn(turn), True

    def active_turn(self):
        with self._lock:
            for turn in reversed(list(self._turns.values())):
                if not is_terminal_status(turn["status"]):
                    return self._copy_turn(turn)
            return None

    @property
    def event_logging_enabled(self):
        return self._events_path is not None

    def get_turn(self, turn_id):
        with self._lock:
            turn = self._turns.get(turn_id)
            return None if turn is None else self._copy_turn(turn)

    def _trim_turns(self):
        while len(self._turns) > self._max_turns:
            self._turns.popitem(last=False)

    @staticmethod
    def _copy_turn(turn):
        copy = dict(turn)
        copy["events"] = [dict(event) for event in turn["events"]]
        return copy

    def _append_safe_log(self, event):
        if self._events_path is None:
            return
        safe = {key: event[key] for key in _LOG_FIELDS if key in event}
        try:
            with self._events_path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(safe, ensure_ascii=False) + "\n")
        except OSError:
            self._events_path = None


def is_terminal_status(status):
    """Tell clients whether a turn no longer expects bridge events."""
    return status in _TERMINAL_STATUSES
