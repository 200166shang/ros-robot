#!/usr/bin/env python3
"""Repeatable voice-to-tracking acceptance probe for the isolated demo domain.

The person detection injected below is synthetic. Camera capture, NPU inference,
web streams, ASR, Qwen, Agent command handling, TTS, and the tracker node remain
real; the synthetic detection only makes the final dry-run tracker response
deterministic when no person is physically in front of the camera.
"""

import json
import time
from urllib.request import urlopen

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import Log, ParameterType
from rcl_interfaces.srv import GetParameters
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from robot_interfaces.msg import Det, Dets
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
from std_srvs.srv import Trigger


EXPECTED_TRANSCRIPT = "开始人物跟踪"
EXPECTED_COMMAND = "start_tracking"
WEB_STATUS_URL = "http://127.0.0.1:8080/api/status"


class AcceptanceFailure(RuntimeError):
    pass


class VoiceTrackingAcceptanceProbe(Node):
    def __init__(self):
        super().__init__("voice_tracking_acceptance_probe")
        self.transcripts = []
        self.commands = []
        self.responses = []
        self.motion_messages = []
        self.preview_logs = []
        self.voice_tts_logs = []
        self.voice_no_play_logs = []
        self.voice_error_logs = []
        self.camera_frames = 0

        self.create_subscription(
            String, "/llm/user_input", lambda msg: self.transcripts.append(msg.data), 10
        )
        self.create_subscription(
            String, "/agent/command", lambda msg: self.commands.append(msg.data), 10
        )
        self.create_subscription(
            String, "/llm/response", lambda msg: self.responses.append(msg.data), 10
        )
        self.create_subscription(
            Twist,
            "/tracking/cmd_vel_safe",
            lambda msg: self.motion_messages.append(msg),
            10,
        )

        sensor_qos = QoSProfile(depth=1)
        sensor_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        sensor_qos.durability = DurabilityPolicy.VOLATILE
        self.create_subscription(
            CompressedImage,
            "/image_raw/compressed",
            self._on_camera_frame,
            sensor_qos,
        )
        self._detection_publisher = self.create_publisher(
            Dets, "/ai_msg_det", sensor_qos
        )
        log_qos = QoSProfile(depth=100)
        log_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        log_qos.durability = DurabilityPolicy.VOLATILE
        self.create_subscription(Log, "/rosout", self._on_log, log_qos)

        self._capture_client = self.create_client(Trigger, "/voice/capture")
        self._tracking_parameter_client = self.create_client(
            GetParameters, "/object_track/get_parameters"
        )

    def _on_camera_frame(self, _message):
        self.camera_frames += 1

    def _on_log(self, message):
        if message.name.endswith("object_track") and "dry-run preview" in message.msg:
            self.preview_logs.append(message.msg)
        if message.name.endswith("voice_frontend") and "TTS WAV generated" in message.msg:
            self.voice_tts_logs.append(message.msg)
        if (
            message.name.endswith("voice_frontend")
            and "play_audio=false; leaving playback disabled" in message.msg
        ):
            self.voice_no_play_logs.append(message.msg)
        if message.name.endswith("voice_frontend") and "voice turn failed" in message.msg:
            self.voice_error_logs.append(message.msg)

    def spin_until(self, predicate, timeout_seconds, description):
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and rclpy.ok():
            if self.voice_error_logs:
                raise AcceptanceFailure(self.voice_error_logs[-1])
            if predicate():
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
        if predicate():
            return True
        raise AcceptanceFailure("timed out waiting for " + description)

    def verify_dry_run_parameter(self):
        if not self._tracking_parameter_client.wait_for_service(timeout_sec=30.0):
            raise AcceptanceFailure("/object_track parameter services are unavailable")
        request = GetParameters.Request()
        request.names = ["dry_run"]
        future = self._tracking_parameter_client.call_async(request)
        self.spin_until(future.done, 10.0, "dry_run parameter response")
        values = future.result().values
        if len(values) != 1 or values[0].type != ParameterType.PARAMETER_BOOL:
            raise AcceptanceFailure("/object_track dry_run parameter is not boolean")
        if not values[0].bool_value:
            raise AcceptanceFailure("unsafe configuration: /object_track dry_run is false")

    def wait_for_stack(self):
        if not self._capture_client.wait_for_service(timeout_sec=60.0):
            raise AcceptanceFailure("/voice/capture service is unavailable")
        self.spin_until(
            lambda: (
                self.count_subscribers("/llm/user_input") > 0
                and self.count_publishers("/llm/response") > 0
                and self.count_subscribers("/agent/command") > 0
                and self.count_publishers("/agent/response") > 0
                and self.count_subscribers("/ai_msg_det") > 0
            ),
            60.0,
            "Qwen bridge, Agent, and detector graph",
        )
        self.verify_dry_run_parameter()

    def get_web_status(self):
        try:
            with urlopen(WEB_STATUS_URL, timeout=1.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def verify_web_streams(self):
        status = self.get_web_status()
        if not isinstance(status, dict):
            raise AcceptanceFailure("web viewer /api/status is unavailable")
        for stream_name in ("raw", "detection"):
            stream = status.get(stream_name)
            if not isinstance(stream, dict) or stream.get("connected") is not True:
                raise AcceptanceFailure(
                    "web viewer {} stream is not receiving frames".format(stream_name)
                )
        return status

    def publish_synthetic_person_detection(self):
        message = Dets()
        message.image_width = 640
        message.image_height = 480
        detection = Det()
        detection.x1 = 450
        detection.y1 = 100
        detection.x2 = 510
        detection.y2 = 170
        detection.confidence = 0.95
        detection.class_name = "person"
        detection.class_id = 0
        detection.object_id = 1
        message.detections = [detection]
        self._detection_publisher.publish(message)

    def run_acceptance(self):
        self.wait_for_stack()

        transcript_count = len(self.transcripts)
        command_count = len(self.commands)
        response_count = len(self.responses)
        tts_count = len(self.voice_tts_logs)
        no_play_count = len(self.voice_no_play_logs)
        request_future = self._capture_client.call_async(Trigger.Request())
        self.spin_until(request_future.done, 30.0, "/voice/capture acknowledgement")
        capture_response = request_future.result()
        if capture_response is None or not capture_response.success:
            reason = "no response" if capture_response is None else capture_response.message
            raise AcceptanceFailure("voice capture request failed: " + reason)
        print("capture_prompt=" + capture_response.message, flush=True)

        self.spin_until(
            lambda: (
                len(self.transcripts) > transcript_count
                and len(self.commands) > command_count
                and len(self.responses) > response_count
                and len(self.voice_tts_logs) > tts_count
                and len(self.voice_no_play_logs) > no_play_count
            ),
            300.0,
            "ASR -> Qwen -> Agent -> response -> local TTS",
        )

        transcript = self.transcripts[-1]
        if transcript != EXPECTED_TRANSCRIPT:
            raise AcceptanceFailure(
                "unexpected ASR transcript: {!r}".format(transcript)
            )
        new_commands = self.commands[command_count:]
        if new_commands != [EXPECTED_COMMAND]:
            raise AcceptanceFailure(
                "expected exactly one start_tracking command; received {!r}".format(
                    new_commands
                )
            )
        response = self.responses[-1]
        for phrase in ("Agent 已确认", "相机采集开启", "人物跟踪开启"):
            if phrase not in response:
                raise AcceptanceFailure(
                    "Agent confirmation is missing {!r}: {!r}".format(phrase, response)
                )

        self.spin_until(lambda: self.camera_frames >= 3, 20.0, "C270 camera frames")
        self.spin_until(
            lambda: self._web_streams_connected(),
            20.0,
            "raw and NPU detection web streams",
        )
        web_status = self.verify_web_streams()

        preview_count = len(self.preview_logs)
        deadline = time.monotonic() + 5.0
        while (
            time.monotonic() < deadline
            and len(self.preview_logs) <= preview_count
            and rclpy.ok()
        ):
            self.publish_synthetic_person_detection()
            rclpy.spin_once(self, timeout_sec=0.1)
        if len(self.preview_logs) <= preview_count:
            raise AcceptanceFailure("synthetic person did not produce a dry-run preview")
        if self.motion_messages:
            raise AcceptanceFailure(
                "unexpected Twist messages on /tracking/cmd_vel_safe"
            )
        if self.count_publishers("/tracking/cmd_vel_safe") != 0:
            raise AcceptanceFailure(
                "dry-run tracker unexpectedly created a Twist publisher"
            )

        print("voice_transcript=" + transcript)
        print("agent_command=" + self.commands[-1])
        print("agent_confirmation=" + response)
        print("camera_frames=" + str(self.camera_frames))
        print("web_stream_status=" + json.dumps(web_status, ensure_ascii=False))
        print("dry_run_parameter=true")
        print("tracker_fixture=synthetic_person")
        print("dry_run_previews=" + json.dumps(self.preview_logs[-3:], ensure_ascii=False))
        print("motion_topic_messages=0")
        print("tts_generated=true_playback=disabled")
        print("acceptance=PASS")

    def _web_streams_connected(self):
        status = self.get_web_status()
        return bool(
            isinstance(status, dict)
            and status.get("raw", {}).get("connected") is True
            and status.get("detection", {}).get("connected") is True
        )


def main(args=None):
    rclpy.init(args=args)
    node = VoiceTrackingAcceptanceProbe()
    try:
        node.run_acceptance()
        return 0
    except Exception as error:
        print("acceptance=FAIL")
        print("failure={} : {}".format(type(error).__name__, error))
        return 2
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
