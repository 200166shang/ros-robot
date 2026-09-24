"""Tests for correlated UI turns and privacy-preserving event records."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "ros2_ws" / "src" / "web_video_server"),
)

from web_video_server.turn_store import (
    AudioResponseUnavailable,
    TurnEventStore,
    TurnInProgressError,
    is_terminal_status,
)


class TurnEventStoreTests(unittest.TestCase):
    def test_turn_state_is_correlated_and_active_until_terminal(self):
        store = TurnEventStore()
        turn = store.create_turn("turn-1", "private question")

        self.assertEqual(turn["status"], "queued")
        self.assertEqual(store.active_turn()["turn_id"], "turn-1")
        with self.assertRaises(TurnInProgressError):
            store.create_turn("turn-2", "second question")

        updated = store.ingest_event({
            "turn_id": "turn-1",
            "run_id": store.run_id,
            "stage": "inference",
            "status": "started",
            "elapsed_ms": 10,
        })
        self.assertEqual(updated["stage"], "inference")
        self.assertEqual(updated["elapsed_ms"], 10)

        completed = store.ingest_event({
            "turn_id": "turn-1",
            "run_id": store.run_id,
            "stage": "succeeded",
            "status": "succeeded",
            "elapsed_ms": 500,
            "response_text": "private answer",
        })
        self.assertEqual(completed["response_text"], "private answer")
        self.assertIsNone(store.active_turn())
        self.assertTrue(is_terminal_status(completed["status"]))

        second = store.create_turn("turn-2", "second question")
        self.assertEqual(second["status"], "queued")

    def test_browser_audio_state_does_not_replace_text_turn_status(self):
        store = TurnEventStore()
        store.create_turn("turn-audio", "question")
        with self.assertRaises(AudioResponseUnavailable):
            store.request_audio("turn-audio")

        store.ingest_event({
            "turn_id": "turn-audio",
            "run_id": store.run_id,
            "stage": "succeeded",
            "status": "succeeded",
            "response_text": "answer",
        })
        queued, should_publish = store.request_audio("turn-audio")
        self.assertTrue(should_publish)
        self.assertEqual(queued["audio_status"], "queued")
        duplicate, should_publish_again = store.request_audio("turn-audio")
        self.assertFalse(should_publish_again)
        self.assertEqual(duplicate["audio_status"], "queued")

        generating = store.ingest_event({
            "turn_id": "turn-audio",
            "run_id": store.run_id,
            "stage": "audio",
            "status": "generating",
            "audio_status": "generating",
        })
        self.assertEqual(generating["status"], "succeeded")
        self.assertEqual(generating["audio_status"], "generating")
        ready = store.ingest_event({
            "turn_id": "turn-audio",
            "run_id": store.run_id,
            "stage": "audio",
            "status": "ready",
            "audio_status": "ready",
            "elapsed_ms": 17,
        })
        self.assertEqual(ready["status"], "succeeded")
        self.assertEqual(ready["audio_status"], "ready")
        self.assertEqual(ready["audio_elapsed_ms"], 17)

    def test_events_from_other_runs_and_unknown_turns_are_ignored(self):
        store = TurnEventStore()
        store.create_turn("turn-1", "hello")

        self.assertIsNone(store.ingest_event({
            "turn_id": "turn-1",
            "run_id": "another-run",
            "stage": "succeeded",
            "status": "succeeded",
        }))
        self.assertIsNone(store.ingest_event({
            "turn_id": "unknown",
            "run_id": store.run_id,
            "stage": "succeeded",
            "status": "succeeded",
        }))
        self.assertEqual(store.get_turn("turn-1")["status"], "queued")

    def test_event_file_never_contains_user_or_assistant_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TurnEventStore(run_log_dir=temp_dir)
            store.create_turn("turn-1", "unique private user phrase")
            store.ingest_event({
                "turn_id": "turn-1",
                "run_id": store.run_id,
                "stage": "succeeded",
                "status": "succeeded",
                "response_text": "unique private assistant phrase",
                "elapsed_ms": 42,
                "event_time_utc": "x" * 1000,
            })
            run_dir = Path(temp_dir) / store.run_id
            manifest = json.loads((run_dir / "manifest.json").read_text())
            log_lines = (run_dir / "events.jsonl").read_text().splitlines()
            log_text = "\n".join(log_lines)

        self.assertFalse(manifest["content_logging"])
        self.assertNotIn("unique private user phrase", log_text)
        self.assertNotIn("unique private assistant phrase", log_text)
        self.assertIn('"elapsed_ms": 42', log_text)
        self.assertIn('"turn_id": "turn-1"', log_text)
        self.assertLessEqual(
            len(json.loads(log_lines[-1])["event_time_utc"]), 64
        )


if __name__ == "__main__":
    unittest.main()
