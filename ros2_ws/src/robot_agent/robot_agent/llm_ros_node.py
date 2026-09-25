"""ROS 2 text bridge to the local Qwen completion client."""

import json
import threading
import time

import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from .llama_client import LlamaCompletionClient
from .llm_adapter import DecisionKind, decide_model_output
from .navigation_client import NAVIGATION_MODEL_FUNCTIONS
from robot_head.catalog import MODEL_FUNCTIONS, MOTION_CATALOG

DEFAULT_SYSTEM_PROMPT = (
    "你是小沫，科研 AI。技术严谨，非技术诗意，主动启发，兼精准共情。"
    "[格式]中文流畅无机械感，仅用逗号句号问号，禁用表情。"
    "出结构化 JSON：fc：函数列表（含参，按序）；res：第一人称回复，普通对话补内容。"
)
REJECTION_TEXT = "我理解你的请求，但当前原型不执行设备控制指令。"
SERVICE_ERROR_TEXT = "本地模型服务暂不可用，请稍后重试。"
COMMAND_TIMEOUT_TEXT = "Agent 未及时确认命令结果，无法确认是否执行。"
NAVIGATION_SYSTEM_PROMPT = (
    "[仅限本次显式启用的导航仿真] 可用函数名只有 "
    "navigate_to_goal_a、navigate_to_goal_b、cancel_navigation、navigation_status。"
    "目标是固定地点，禁止生成坐标或其他参数。导航只在 Mac 上的 Nav2 理想仿真中运行，"
    "不是实体移动；任务提交不等于已经到达。只有用户明确要求前往目标A或目标B时才调用导航，"
    "只有用户明确要求取消时才调用 cancel_navigation，查询状态使用 navigation_status。"
)
APPROVED_FUNCTION_ALLOWLIST = {
    ("query_camera_status", "query_person_tracking_status"): "status",
    "start_receiving_image": "start_camera",
    "stop_camera_collection": "stop_camera",
    "start_tracking": "start_tracking",
}
for _head_function in MODEL_FUNCTIONS:
    APPROVED_FUNCTION_ALLOWLIST[_head_function] = _head_function



class LlmRosNode(Node):
    """Text adapter; command output exists only when explicitly enabled."""

    def __init__(self):
        super().__init__("qwen_ros_bridge")
        endpoint = self.declare_parameter(
            "llama_endpoint", "http://127.0.0.1:18080/completion"
        ).value
        system_prompt = self.declare_parameter(
            "system_prompt", DEFAULT_SYSTEM_PROMPT
        ).value
        timeout_seconds = self.declare_parameter(
            "request_timeout_seconds", 120.0
        ).value
        n_predict = self.declare_parameter("n_predict", 128).value
        enable_commands = self.declare_parameter("enable_commands", False).value
        enable_simulated_navigation = bool(
            self.declare_parameter("enable_simulated_navigation", False).value
        )
        command_timeout = self.declare_parameter("command_timeout_seconds", 5.0).value

        self._system_prompt = str(system_prompt)
        if enable_simulated_navigation:
            self._system_prompt += NAVIGATION_SYSTEM_PROMPT
        self._client = LlamaCompletionClient(
            endpoint=endpoint,
            timeout_seconds=float(timeout_seconds),
            n_predict=int(n_predict),
        )
        function_allowlist = dict(
            APPROVED_FUNCTION_ALLOWLIST if enable_commands else {}
        )
        if enable_simulated_navigation:
            function_allowlist.update(NAVIGATION_MODEL_FUNCTIONS)
        self._function_allowlist = function_allowlist or None
        self._command_timeout = float(command_timeout)
        self._command_condition = threading.Condition()
        self._pending_command = None
        self._pending_response = None
        self._command_publisher = None

        self._response_publisher = self.create_publisher(
            String, "/llm/response", 10
        )
        self._turn_event_publisher = self.create_publisher(
            String, "/llm/turn/event", 10
        )
        self.create_subscription(
            String, "/llm/user_input", self._on_user_input, 10
        )
        self.create_subscription(
            String, "/llm/turn/request", self._on_turn_request, 10
        )
        if enable_commands or enable_simulated_navigation:
            self._command_publisher = self.create_publisher(
                String, "/agent/command", 10
            )
            self._agent_response_callback_group = ReentrantCallbackGroup()
            self.create_subscription(
                String,
                "/agent/response",
                self._on_agent_response,
                10,
                callback_group=self._agent_response_callback_group,
            )

        command_modes = []
        if enable_commands:
            command_modes.append("approved device/software commands")
        if enable_simulated_navigation:
            command_modes.append("fixed-location Nav2 simulation")
        command_mode = ", ".join(command_modes) if command_modes else "disabled"
        self.get_logger().info(
            "Qwen ROS bridge ready: /llm/user_input -> /llm/response; "
            f"approved command mode={command_mode}"
        )

    def _on_user_input(self, message):
        self._process_user_input(message.data)

    def _on_turn_request(self, message):
        try:
            payload = json.loads(message.data)
        except (TypeError, ValueError):
            self.get_logger().warning("discarded malformed turn request")
            return

        if not isinstance(payload, dict):
            self.get_logger().warning("discarded turn request with invalid shape")
            return

        if payload.get("schema_version") != 1:
            self.get_logger().warning("discarded unsupported turn request version")
            return
        turn_id = payload.get("turn_id")
        run_id = payload.get("run_id")
        text = payload.get("text")
        if (
            not isinstance(turn_id, str)
            or not turn_id
            or len(turn_id) > 64
            or not isinstance(run_id, str)
            or not run_id
            or len(run_id) > 64
            or not isinstance(text, str)
            or len(text) > 4000
        ):
            self.get_logger().warning("discarded invalid turn request fields")
            return
        self._process_user_input(text, turn_id=turn_id, run_id=run_id)

    def _process_user_input(self, user_text, turn_id=None, run_id=None):
        started_at = time.monotonic()
        if not user_text.strip():
            response_text = "请先输入要咨询的内容。"
            if turn_id is None:
                self._publish_response(response_text)
            if turn_id is not None:
                self._publish_turn_event(
                    turn_id, run_id, "failed", "failed",
                    error_code="empty_input",
                    response_text=response_text,
                    started_at=started_at,
                )
            return

        if turn_id is not None:
            self._publish_turn_event(
                turn_id, run_id, "inference", "started", started_at=started_at
            )
        try:
            raw_output = self._client.complete(self._system_prompt, user_text)
            decision = decide_model_output(
                raw_output, function_allowlist=self._function_allowlist
            )
        except Exception as error:
            self.get_logger().error(
                f"local inference failed ({type(error).__name__})"
            )
            response_text = SERVICE_ERROR_TEXT
            if turn_id is None:
                self._publish_response(response_text)
            if turn_id is not None:
                self._publish_turn_event(
                    turn_id, run_id, "failed", "failed",
                    error_code="llm_unavailable",
                    response_text=response_text,
                    started_at=started_at,
                )
            return

        error_code = None
        final_status = "succeeded"
        if decision.kind is DecisionKind.CHAT_ONLY:
            response_text = (decision.model_response or "").strip()
            if not response_text:
                response_text = REJECTION_TEXT
        elif decision.kind is DecisionKind.COMMAND and decision.command:
            if turn_id is not None:
                self._publish_turn_event(
                    turn_id, run_id, "executing", "started",
                    command=decision.command,
                    started_at=started_at,
                )
            response_payload = self._send_command_and_wait(decision.command)
            if response_payload is None:
                response_text = COMMAND_TIMEOUT_TEXT
                final_status = "failed"
                error_code = "agent_timeout"
            elif response_payload.get("success") is not True:
                response_text = "Agent 未确认该命令执行成功。"
                final_status = "failed"
                error_code = "agent_rejected"
            else:
                response_text = self._confirmed_action_text(
                    decision.command, response_payload
                )
        elif decision.kind is DecisionKind.REJECTED:
            self.get_logger().warning(
                f"model action/output rejected ({decision.reason or decision.kind.value})"
            )
            response_text = REJECTION_TEXT
            final_status = "rejected"
            error_code = decision.reason or "action_rejected"
        else:
            self.get_logger().warning(
                f"model action/output rejected ({decision.reason or decision.kind.value})"
            )
            response_text = REJECTION_TEXT

        if turn_id is None:
            self._publish_response(response_text)
        if turn_id is not None:
            self._publish_turn_event(
                turn_id, run_id, final_status, final_status,
                error_code=error_code,
                response_text=response_text,
                command=decision.command,
                started_at=started_at,
            )

    def _publish_turn_event(
        self, turn_id, run_id, stage, status, *,
        error_code=None, response_text=None, command=None, started_at=None
    ):
        event = {
            "schema_version": 1,
            "turn_id": turn_id,
            "run_id": run_id,
            "stage": stage,
            "status": status,
            "event_time_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime()
            ) + "Z",
        }
        if error_code:
            event["error_code"] = str(error_code)[:64]
        if response_text is not None:
            event["response_text"] = response_text[:12000]
        if command:
            event["command"] = command
        if started_at is not None:
            event["elapsed_ms"] = max(
                0, int((time.monotonic() - started_at) * 1000)
            )
        message = String()
        message.data = json.dumps(event, ensure_ascii=False)
        self._turn_event_publisher.publish(message)

    def _send_command_and_wait(self, command):
        if self._command_publisher is None:
            return None

        with self._command_condition:
            self._pending_command = command
            self._pending_response = None

        message = String()
        message.data = command
        self._command_publisher.publish(message)

        with self._command_condition:
            received = self._command_condition.wait_for(
                lambda: self._pending_response is not None,
                timeout=self._command_timeout,
            )
            response = self._pending_response
            self._pending_command = None
            self._pending_response = None
        return response if received else None

    def _on_agent_response(self, message):
        try:
            payload = json.loads(message.data)
        except (TypeError, ValueError):
            return
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("command"), str)
            or not isinstance(payload.get("success"), bool)
        ):
            return

        with self._command_condition:
            if payload["command"] == self._pending_command:
                self._pending_response = payload
                self._command_condition.notify_all()

    @staticmethod
    def _confirmed_action_text(command, payload):
        if command in NAVIGATION_MODEL_FUNCTIONS.values():
            navigation = payload.get("navigation") or {}
            status = navigation.get("status", "unknown")
            task_id = navigation.get("task_id")
            if command.startswith("navigate_to_"):
                location = navigation.get("location_label") or command[
                    len("navigate_to_"):
                ]
                task_text = "，任务编号 {}".format(task_id) if task_id else ""
                return (
                    "已向 Nav2 理想仿真提交前往「{}」的任务{}，当前状态：{}。"
                    "这是 Mac 上的虚拟导航，不会驱动实体底盘；任务提交不代表已到达。"
                ).format(location, task_text, status)
            if command == "cancel_navigation":
                return "已向 Nav2 仿真发送取消请求，当前状态：{}。取消完成以任务终态为准。".format(
                    status
                )
            return "当前 Nav2 仿真导航状态：{}。{}".format(
                status,
                "任务编号 {}。".format(task_id) if task_id else "当前没有导航任务。",
            )
        if command in MODEL_FUNCTIONS:
            head = payload.get("head_state") or {}
            pitch = head.get("pitch_deg")
            yaw = head.get("yaw_deg")
            posture = ''
            if isinstance(pitch, (int, float)) and isinstance(yaw, (int, float)):
                posture = '当前仿真角度为俯仰 {}°、偏航 {}°。'.format(
                    round(pitch, 1), round(yaw, 1))
            label = MOTION_CATALOG[command].label
            return (
                '虚拟头部已完成「{}」仿真。{}'
                '此状态由网页端渲染，未驱动实体舵机。'
            ).format(label, posture)

        camera_value = payload.get("camera_enabled")
        tracking_value = payload.get("tracking_enabled")
        camera = "开启" if camera_value is True else "关闭" if camera_value is False else "未知"
        tracking = "开启" if tracking_value is True else "关闭" if tracking_value is False else "未知"
        return (
            f"Agent 已确认「{command}」。软件记录：相机采集{camera}，"
            f"人物跟踪{tracking}。这是软件状态，不代表硬件传感器已确认。"
        )

    def _publish_response(self, text):
        response = String()
        response.data = text
        self._response_publisher.publish(response)


def main(args=None):
    rclpy.init(args=args)
    node = LlmRosNode()
    executor = MultiThreadedExecutor(num_threads=2)
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
