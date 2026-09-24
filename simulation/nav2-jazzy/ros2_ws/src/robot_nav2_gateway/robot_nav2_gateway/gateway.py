import base64
import json
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import rclpy
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid, Path
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import Buffer, TransformListener


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def yaw_to_quaternion(yaw):
    return (0.0, 0.0, math.sin(yaw / 2.0), math.cos(yaw / 2.0))


class NavigationGateway(Node):
    """Expose a narrow HTTP API for real Nav2 actions in an ideal loopback world."""

    def __init__(self):
        super().__init__("robot_nav2_http_gateway")
        self.declare_parameter("http_port", 18091)
        port = int(self.get_parameter("http_port").value)
        self._lock = threading.RLock()
        self._frame_id = "map"
        self._base_frame_id = "base_footprint"
        self._clearance_m = 0.30
        self._max_search_m = 2.0
        self._location_seeds = []
        self._locations = {}
        self._map = None
        self._path = []
        self._pose_initialized = False
        self._initial_pose_published_at = 0.0
        self._tasks = {}
        self._active_task_id = None
        self._goal_handles = {}
        self._action_client = ActionClient(self, NavigateToPose, "navigate_to_pose")
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        map_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(OccupancyGrid, "map", self._on_map, map_qos)
        self.create_subscription(Path, "plan", self._on_plan, 10)
        self._initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, "initialpose", 10
        )
        self.create_timer(0.5, self._initialize_pose)
        self.create_timer(1.0, self._monitor_tasks)

        share_dir = get_package_share_directory("robot_nav2_gateway")
        with open(os.path.join(share_dir, "config", "locations.json"),
                  "r", encoding="utf-8") as config_file:
            config = json.load(config_file)
        self._frame_id = str(config["frame_id"])
        self._base_frame_id = str(config["base_frame_id"])
        self._clearance_m = float(config["clearance_m"])
        self._max_search_m = float(config["max_search_m"])
        self._location_seeds = config["locations"]
        if not self._location_seeds or self._location_seeds[0].get("id") != "start":
            raise ValueError("locations.json must begin with the fixed start location")

        self._web_path = os.path.join(share_dir, "web", "index.html")
        self._http_server = ThreadingHTTPServer(("0.0.0.0", port), self._handler_type())
        self._http_server.daemon_threads = True
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever,
            name="nav2-http-server",
            daemon=True,
        )
        self._http_thread.start()
        self.get_logger().info(
            "HTTP gateway listening on port %d; Nav2 backend is loopback" % port
        )

    def _handler_type(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format_string, *args):
                gateway.get_logger().info("HTTP " + format_string % args)

            def _send(self, status_code, payload,
                      content_type="application/json; charset=utf-8"):
                if isinstance(payload, bytes):
                    body = payload
                else:
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/":
                    try:
                        with open(gateway._web_path, "rb") as web_file:
                            self._send(200, web_file.read(), "text/html; charset=utf-8")
                    except OSError:
                        self._send(500, {"error": "web UI unavailable"})
                    return
                if path == "/healthz":
                    health = gateway.health_snapshot()
                    self._send(200 if health["ready"] else 503, health)
                    return
                if path == "/api/v1/navigation/map":
                    payload = gateway.map_snapshot()
                    self._send(200 if payload else 503,
                               payload or {"error": "map unavailable"})
                    return
                if path == "/api/v1/navigation/state":
                    self._send(200, gateway.state_snapshot())
                    return
                if path == "/api/v1/navigation/locations":
                    self._send(200, gateway.locations_snapshot())
                    return
                parts = path.strip("/").split("/")
                if (len(parts) == 5
                        and parts[:3] == ["api", "v1", "navigation"]
                        and parts[3] == "tasks"):
                    task = gateway.task_snapshot(parts[4])
                    self._send(200 if task else 404, task or {"error": "task not found"})
                    return
                self._send(404, {"error": "not found"})

            def do_POST(self):
                path = urlparse(self.path).path
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send(400, {"error": "invalid content length"})
                    return
                if length < 0 or length > 4096:
                    self._send(413, {"error": "request body must be at most 4096 bytes"})
                    return
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send(400, {"error": "body must be valid JSON"})
                    return
                if not isinstance(body, dict):
                    self._send(400, {"error": "body must be a JSON object"})
                    return
                if path == "/api/v1/navigation/tasks":
                    if set(body) != {"location_id"} or not isinstance(body["location_id"], str):
                        self._send(400, {"error": "provide only a string location_id"})
                        return
                    status, payload = gateway.start_navigation(body["location_id"])
                    self._send(status, payload)
                    return
                parts = path.strip("/").split("/")
                if (len(parts) == 6
                        and parts[:3] == ["api", "v1", "navigation"]
                        and parts[3] == "tasks"
                        and parts[5] == "cancel"):
                    status, payload = gateway.cancel_navigation(parts[4])
                    self._send(status, payload)
                    return
                self._send(404, {"error": "not found"})

        return Handler

    def destroy_node(self):
        if hasattr(self, "_http_server"):
            self._http_server.shutdown()
            self._http_server.server_close()
        super().destroy_node()

    def _on_map(self, message):
        with self._lock:
            self._map = message
            self._locations = self._resolve_locations(message)
        if not self._locations:
            self.get_logger().error(
                "No configured destination has sufficient free-space clearance"
            )
        else:
            self.get_logger().info(
                "Loaded map %dx%d; validated %d named locations"
                % (message.info.width, message.info.height, len(self._locations))
            )

    def _on_plan(self, message):
        points = []
        for stamped_pose in message.poses:
            pose = stamped_pose.pose
            q = pose.orientation
            yaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            points.append([pose.position.x, pose.position.y, yaw])
        with self._lock:
            self._path = points

    @staticmethod
    def _origin_yaw(origin):
        q = origin.orientation
        return math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )

    def _world_to_cell(self, grid, x, y):
        origin = grid.info.origin
        yaw = self._origin_yaw(origin)
        dx = x - origin.position.x
        dy = y - origin.position.y
        local_x = math.cos(yaw) * dx + math.sin(yaw) * dy
        local_y = -math.sin(yaw) * dx + math.cos(yaw) * dy
        return int(local_x / grid.info.resolution), int(local_y / grid.info.resolution)

    def _cell_to_world(self, grid, col, row):
        origin = grid.info.origin
        yaw = self._origin_yaw(origin)
        local_x = (col + 0.5) * grid.info.resolution
        local_y = (row + 0.5) * grid.info.resolution
        return (
            origin.position.x + math.cos(yaw) * local_x - math.sin(yaw) * local_y,
            origin.position.y + math.sin(yaw) * local_x + math.cos(yaw) * local_y,
        )

    def _cell_is_clear(self, grid, col, row, radius):
        width = grid.info.width
        height = grid.info.height
        if col < radius or row < radius or col >= width - radius or row >= height - radius:
            return False
        for y in range(row - radius, row + radius + 1):
            start = y * width + col - radius
            end = y * width + col + radius + 1
            if any(value != 0 for value in grid.data[start:end]):
                return False
        return True

    def _resolve_locations(self, grid):
        resolution = grid.info.resolution
        if resolution <= 0:
            return {}
        clearance = max(1, math.ceil(self._clearance_m / resolution))
        search_limit = max(1, math.ceil(self._max_search_m / resolution))
        resolved = {}
        for seed in self._location_seeds:
            preferred_col, preferred_row = self._world_to_cell(
                grid, float(seed["x"]), float(seed["y"])
            )
            chosen = None
            for radius in range(search_limit + 1):
                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        if max(abs(dx), abs(dy)) != radius:
                            continue
                        col = preferred_col + dx
                        row = preferred_row + dy
                        if not self._cell_is_clear(grid, col, row, clearance):
                            continue
                        x, y = self._cell_to_world(grid, col, row)
                        if any(math.hypot(x - item["x"], y - item["y"]) < 0.75
                               for item in resolved.values()):
                            continue
                        chosen = {
                            "id": seed["id"],
                            "label": seed["label"],
                            "x": x,
                            "y": y,
                            "yaw": float(seed["yaw"]),
                        }
                        break
                    if chosen:
                        break
                if chosen:
                    break
            if chosen:
                resolved[chosen["id"]] = chosen
        if "start" not in resolved:
            return {}
        return resolved

    def _initial_pose_message(self):
        start = self._locations.get("start")
        if start is None:
            return None
        message = PoseWithCovarianceStamped()
        message.header.frame_id = self._frame_id
        message.header.stamp = self.get_clock().now().to_msg()
        message.pose.pose.position.x = start["x"]
        message.pose.pose.position.y = start["y"]
        qx, qy, qz, qw = yaw_to_quaternion(start["yaw"])
        message.pose.pose.orientation.x = qx
        message.pose.pose.orientation.y = qy
        message.pose.pose.orientation.z = qz
        message.pose.pose.orientation.w = qw
        message.pose.covariance[0] = 0.25
        message.pose.covariance[7] = 0.25
        message.pose.covariance[35] = 0.0685
        return message

    def _initialize_pose(self):
        with self._lock:
            if (self._map is None or "start" not in self._locations
                    or self._pose_initialized):
                return
        try:
            self._tf_buffer.lookup_transform(
                self._frame_id, self._base_frame_id, rclpy.time.Time()
            )
            with self._lock:
                self._pose_initialized = True
            self.get_logger().info("Loopback initial pose is visible in TF")
            return
        except Exception:
            pass
        now = time.monotonic()
        if now - self._initial_pose_published_at >= 1.0:
            message = self._initial_pose_message()
            if message is not None:
                self._initial_pose_pub.publish(message)
                self._initial_pose_published_at = now

    def _monitor_tasks(self):
        with self._lock:
            for task_id, task in list(self._tasks.items()):
                if (task["status"] == "submitting"
                        and time.monotonic() - task["_created_monotonic"] > 20):
                    task["status"] = "failed"
                    task["result"] = "failed"
                    task["error"] = "Nav2 did not answer the goal request within 20 seconds"
                    task["updated_at"] = utc_now()
                    self._active_task_id = None
                    self.get_logger().error("Navigation task %s timed out at submission" % task_id)

    def health_snapshot(self):
        with self._lock:
            map_ready = self._map is not None and "start" in self._locations
            pose_ready = self._pose_initialized
        action_ready = self._action_client.server_is_ready()
        return {
            "schema_version": 1,
            "ready": bool(map_ready and pose_ready and action_ready),
            "backend": "nav2-jazzy-loopback",
            "simulation": "idealized-loopback-no-physics",
            "map_ready": map_ready,
            "initial_pose_ready": pose_ready,
            "navigate_to_pose_ready": action_ready,
        }

    def map_snapshot(self):
        with self._lock:
            grid = self._map
        if grid is None:
            return None
        origin = grid.info.origin
        yaw = self._origin_yaw(origin)
        raw = bytes((int(value) & 0xff) for value in grid.data)
        return {
            "frame_id": grid.header.frame_id,
            "width": grid.info.width,
            "height": grid.info.height,
            "resolution": grid.info.resolution,
            "origin": {"x": origin.position.x, "y": origin.position.y, "yaw": yaw},
            "encoding": "int8-base64",
            "data": base64.b64encode(raw).decode("ascii"),
        }

    def locations_snapshot(self):
        with self._lock:
            return {
                "schema_version": 1,
                "frame_id": self._frame_id,
                "locations": [dict(item) for item in self._locations.values()],
            }

    def _current_pose(self):
        try:
            transform = self._tf_buffer.lookup_transform(
                self._frame_id, self._base_frame_id, rclpy.time.Time()
            ).transform
        except Exception:
            return None
        q = transform.rotation
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        return {
            "x": transform.translation.x,
            "y": transform.translation.y,
            "yaw": yaw,
        }

    def state_snapshot(self):
        pose = self._current_pose()
        with self._lock:
            task = self._tasks.get(self._active_task_id) if self._active_task_id else None
            path = [list(item) for item in self._path]
            active_task = None if task is None else {
                key: value for key, value in task.items() if not key.startswith("_")
            }
        state = {
            "schema_version": 1,
            "backend": "nav2-jazzy-loopback",
            "simulation": "idealized-loopback-no-physics",
            "pose": pose,
            "path": path,
            "active_task": active_task,
        }
        state.update(self.health_snapshot())
        return state

    def task_snapshot(self, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            return {key: value for key, value in task.items() if not key.startswith("_")}

    def start_navigation(self, location_id):
        with self._lock:
            location = self._locations.get(location_id)
            if location is None:
                return 422, {"error": "location_id is not in the validated location list"}
            if self._active_task_id is not None:
                return 409, {
                    "error": "another navigation task is active",
                    "active_task_id": self._active_task_id,
                }
            if self._map is None or not self._pose_initialized:
                return 503, {"error": "map or initial pose is not ready"}
            if not self._action_client.server_is_ready():
                return 503, {"error": "NavigateToPose action server is not ready"}
            task_id = str(uuid.uuid4())
            self._tasks[task_id] = {
                "task_id": task_id,
                "location_id": location_id,
                "location_label": location["label"],
                "status": "submitting",
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "distance_remaining_m": None,
                "result": None,
                "error": None,
                "_created_monotonic": time.monotonic(),
            }
            self._active_task_id = task_id

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = self._frame_id
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = location["x"]
        goal.pose.pose.position.y = location["y"]
        qx, qy, qz, qw = yaw_to_quaternion(location["yaw"])
        goal.pose.pose.orientation.x = qx
        goal.pose.pose.orientation.y = qy
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw
        try:
            future = self._action_client.send_goal_async(
                goal,
                feedback_callback=lambda feedback: self._on_feedback(task_id, feedback),
            )
            future.add_done_callback(
                lambda completed: self._on_goal_response(task_id, completed)
            )
        except Exception as error:
            self._finish_task(task_id, "failed", "goal submission failed: " + type(error).__name__)
            return 503, {"error": "Nav2 goal submission failed"}
        return 202, {
            "task_id": task_id,
            "status": "submitting",
            "location_id": location_id,
        }

    def _on_goal_response(self, task_id, future):
        try:
            goal_handle = future.result()
        except Exception as error:
            self._finish_task(task_id, "failed", "goal response failed: " + type(error).__name__)
            return
        if not goal_handle.accepted:
            self._finish_task(task_id, "failed", "Nav2 rejected the goal")
            return
        with self._lock:
            self._goal_handles[task_id] = goal_handle
            task = self._tasks.get(task_id)
            if task:
                task["status"] = "running"
                task["updated_at"] = utc_now()
        goal_handle.get_result_async().add_done_callback(
            lambda completed: self._on_result(task_id, completed)
        )

    def _on_feedback(self, task_id, wrapped_feedback):
        remaining = float(wrapped_feedback.feedback.distance_remaining)
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task["status"] not in ("succeeded", "failed", "canceled"):
                task["status"] = "running"
                task["distance_remaining_m"] = remaining
                task["updated_at"] = utc_now()

    def _on_result(self, task_id, future):
        try:
            wrapped = future.result()
        except Exception as error:
            self._finish_task(task_id, "failed", "result unavailable: " + type(error).__name__)
            return
        if wrapped.status == GoalStatus.STATUS_SUCCEEDED:
            status = "succeeded"
        elif wrapped.status == GoalStatus.STATUS_CANCELED:
            status = "canceled"
        else:
            status = "failed"
        error_message = getattr(wrapped.result, "error_msg", "") or None
        self._finish_task(task_id, status, error_message)

    def _finish_task(self, task_id, status, error):
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                task["status"] = status
                task["updated_at"] = utc_now()
                task["result"] = status
                task["error"] = error
            self._goal_handles.pop(task_id, None)
            if self._active_task_id == task_id:
                self._active_task_id = None
            while len(self._tasks) > 40:
                oldest = next(iter(self._tasks))
                if oldest == self._active_task_id:
                    break
                self._tasks.pop(oldest)

    def cancel_navigation(self, task_id):
        with self._lock:
            task = self._tasks.get(task_id)
            goal_handle = self._goal_handles.get(task_id)
            if task is None:
                return 404, {"error": "task not found"}
            if task["status"] not in ("running", "accepted") or goal_handle is None:
                return 409, {
                    "error": "task is not currently cancellable",
                    "status": task["status"],
                }
            task["status"] = "canceling"
            task["updated_at"] = utc_now()
        try:
            future = goal_handle.cancel_goal_async()
            future.add_done_callback(
                lambda completed: self._on_cancel_response(task_id, completed)
            )
        except Exception as error:
            with self._lock:
                task["status"] = "running"
                task["error"] = "cancel request failed: " + type(error).__name__
            return 503, {"error": "Nav2 cancel request failed"}
        return 202, {"task_id": task_id, "status": "canceling"}

    def _on_cancel_response(self, task_id, future):
        try:
            accepted = bool(future.result().goals_canceling)
        except Exception:
            accepted = False
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and not accepted:
                task["status"] = "running"
                task["error"] = "Nav2 did not accept cancellation"
                task["updated_at"] = utc_now()


def main():
    rclpy.init()
    node = NavigationGateway()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
