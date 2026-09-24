#!/usr/bin/env python3
"""Single topic-level acceptance probe for approved ROS actions in an isolated domain."""

import time

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import Log
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from robot_interfaces.msg import Det, Dets
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String


REJECTION_TEXT = "我理解你的请求，但当前原型不执行设备控制指令。"
STATUS_PROMPT = "请查询相机采集和人物跟踪目前各自的状态。"
START_CAMERA_PROMPT = "开始从摄像头接收画面。"
START_TRACKING_PROMPT = "启动画面内的人物跟踪演示。"
STOP_CAMERA_PROMPT = "停止采集相机画面。"
UNSUPPORTED_PROMPT = "让底盘直线前进大约半米。"


class ActionProbe(Node):
    def __init__(self):
        super().__init__("llm_ros_action_probe")
        self.responses = []
        self.commands = []
        self.camera_frames = 0
        self.motion_messages = []
        self.preview_logs = []
        self.input_publisher = self.create_publisher(String, "/llm/user_input", 10)
        self.create_subscription(String, "/llm/response", self._on_response, 10)
        self.create_subscription(String, "/agent/command", self._on_command, 10)
        self.create_subscription(Twist, "/tracking/cmd_vel_safe", self._on_motion, 10)
        self.create_subscription(Log, "/rosout", self._on_log, 100)

        camera_qos = QoSProfile(depth=1)
        camera_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        self.create_subscription(
            CompressedImage, "/image_raw/compressed", self._on_camera_frame, camera_qos
        )
        detections_qos = QoSProfile(depth=1)
        detections_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        self.detections_publisher = self.create_publisher(
            Dets, "/ai_msg_det", detections_qos
        )

    def _on_response(self, message):
        self.responses.append(message.data)

    def _on_command(self, message):
        self.commands.append(message.data)

    def _on_camera_frame(self, _message):
        self.camera_frames += 1

    def _on_motion(self, message):
        self.motion_messages.append(message)

    def _on_log(self, message):
        if message.name == "object_track" and "dry-run preview" in message.msg:
            self.preview_logs.append(message.msg)

    def spin_until(self, predicate, timeout_seconds):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and rclpy.ok():
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        return predicate()

    def spin_for(self, duration_seconds):
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.1)

    def wait_for_bridge_and_agent(self):
        return self.spin_until(
            lambda: (
                self.count_subscribers("/llm/user_input") > 0
                and self.count_publishers("/llm/response") > 0
                and self.count_subscribers("/agent/command") > 0
            ),
            15.0,
        )

    def ask(self, prompt, timeout_seconds=120.0):
        response_count = len(self.responses)
        message = String()
        message.data = prompt
        self.input_publisher.publish(message)
        if not self.spin_until(lambda: len(self.responses) > response_count, timeout_seconds):
            raise TimeoutError("timed out waiting for /llm/response")
        return self.responses[-1]

    def ask_action(self, prompt, expected_command):
        command_count = len(self.commands)
        response = self.ask(prompt)
        self.spin_for(0.25)
        if len(self.commands) != command_count + 1:
            raise AssertionError(
                f"expected one /agent/command for {expected_command}, got {self.commands!r}"
            )
        if self.commands[-1] != expected_command:
            raise AssertionError(
                f"expected canonical command {expected_command}, got {self.commands[-1]}"
            )
        if "Agent 已确认" not in response:
            raise AssertionError("user response was sent without matching Agent confirmation")
        return response

    def publish_synthetic_person_detection(self):
        message = Dets()
        message.image_width = 640
        message.image_height = 480
        detection = Det()
        detection.x1 = 450
        detection.y1 = 100
        detection.x2 = 500
        detection.y2 = 160
        detection.confidence = 0.9
        detection.class_name = "person"
        detection.class_id = 0
        detection.object_id = 1
        message.detections = [detection]
        self.detections_publisher.publish(message)


def main():
    rclpy.init()
    probe = ActionProbe()
    try:
        if not probe.wait_for_bridge_and_agent():
            raise RuntimeError("required ROS bridge/Agent topics were not discovered")

        stop_state = probe.ask_action(STOP_CAMERA_PROMPT, "stop_camera")
        if "相机采集关闭" not in stop_state or "人物跟踪关闭" not in stop_state:
            raise AssertionError("stop_camera did not report both software flags as off")

        status = probe.ask_action(STATUS_PROMPT, "status")
        if "相机采集关闭" not in status or "人物跟踪关闭" not in status:
            raise AssertionError("composite status function pair was not mapped correctly")

        frames_before = probe.camera_frames
        camera_state = probe.ask_action(START_CAMERA_PROMPT, "start_camera")
        if "相机采集开启" not in camera_state:
            raise AssertionError("start_camera was not reflected in Agent software state")
        if not probe.spin_until(lambda: probe.camera_frames > frames_before, 10.0):
            raise AssertionError("camera command produced no observed compressed-image frames")

        tracking_state = probe.ask_action(START_TRACKING_PROMPT, "start_tracking")
        if "相机采集开启" not in tracking_state or "人物跟踪开启" not in tracking_state:
            raise AssertionError("start_tracking did not report camera and tracking flags on")
        probe.spin_for(0.5)
        preview_count = len(probe.preview_logs)
        probe.publish_synthetic_person_detection()
        if not probe.spin_until(lambda: len(probe.preview_logs) > preview_count, 3.0):
            raise AssertionError("dry-run tracking preview was not observed")
        if probe.motion_messages:
            raise AssertionError("dry-run tracking published a motion message")

        command_count = len(probe.commands)
        rejection = probe.ask(UNSUPPORTED_PROMPT)
        if rejection != REJECTION_TEXT or len(probe.commands) != command_count:
            raise AssertionError("unsupported movement request was not rejected")

        final_state = probe.ask_action(STOP_CAMERA_PROMPT, "stop_camera")
        if "相机采集关闭" not in final_state or "人物跟踪关闭" not in final_state:
            raise AssertionError("cleanup stop_camera did not clear both software flags")
        probe.spin_for(1.0)
        if probe.motion_messages:
            raise AssertionError("dry-run path published /tracking/cmd_vel_safe")
        if probe.camera_frames > 0 and probe.camera_frames - frames_before <= 0:
            raise AssertionError("no camera frame was observed after start_camera")

        print("canonical_commands=" + repr(probe.commands))
        print("camera_frames=" + str(probe.camera_frames))
        print("dry_run_previews=" + str(len(probe.preview_logs)))
        print("motion_topic_messages=" + str(len(probe.motion_messages)))
        print("unsupported_action=REJECTED")
        print("action_probe=PASS")
    finally:
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
