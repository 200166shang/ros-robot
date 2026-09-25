import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from robot_agent.navigation_client import (
    NavigationClientError,
    NavigationHttpClient,
)


TASK_ID = "4b998721-83f5-4b47-a223-fa58fc9849a4"


class _FakeNav2Handler(BaseHTTPRequestHandler):
    requests = []
    task_status = "running"

    def log_message(self, _format, *_args):
        pass

    def _send(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((self.command, self.path, body))
        if self.path == "/api/v1/navigation/tasks":
            self._send(202, {
                "task_id": TASK_ID,
                "status": "submitting",
                "location_id": body.get("location_id"),
            })
            return
        if self.path.endswith("/cancel"):
            self._send(202, {"task_id": TASK_ID, "status": "canceling"})
            return
        self._send(404, {"error": "not found"})

    def do_GET(self):
        type(self).requests.append((self.command, self.path, None))
        if self.path == "/api/v1/navigation/tasks/" + TASK_ID:
            self._send(200, {
                "task_id": TASK_ID,
                "location_id": "goal_a",
                "status": type(self).task_status,
            })
            return
        self._send(404, {"error": "task not found"})


class TestNavigationHttpClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeNav2Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = "http://127.0.0.1:{}".format(cls.server.server_address[1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        _FakeNav2Handler.requests = []
        _FakeNav2Handler.task_status = "running"
        self.client = NavigationHttpClient(self.endpoint)

    def test_only_loopback_http_endpoints_are_accepted(self):
        for endpoint in (
            "https://127.0.0.1:18092",
            "http://example.com:18092",
            "http://127.0.0.1:18092/path",
            "http://user:password@127.0.0.1:18092",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    NavigationHttpClient(endpoint)

    def test_only_named_allowlisted_destinations_can_be_submitted(self):
        with self.assertRaises(NavigationClientError):
            self.client.start_navigation("../../cmd_vel")
        self.assertEqual(_FakeNav2Handler.requests, [])

        response = self.client.start_navigation("goal_a")
        self.assertEqual(response["task_id"], TASK_ID)
        self.assertEqual(
            _FakeNav2Handler.requests,
            [("POST", "/api/v1/navigation/tasks", {"location_id": "goal_a"})],
        )

    def test_task_status_and_cancel_use_a_validated_task_id(self):
        self.assertEqual(self.client.get_task(TASK_ID)["status"], "running")
        self.assertEqual(
            self.client.cancel_navigation(TASK_ID)["status"], "canceling"
        )
        with self.assertRaises(NavigationClientError):
            self.client.get_task("not-a-task-id")

    def test_http_errors_are_reported_without_failing_open(self):
        with self.assertRaisesRegex(NavigationClientError, "HTTP 404"):
            self.client._request(
                "/not-found", method="GET", expected_status=200
            )


if __name__ == "__main__":
    unittest.main()
