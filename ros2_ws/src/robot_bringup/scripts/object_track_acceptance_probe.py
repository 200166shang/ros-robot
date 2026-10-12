#!/usr/bin/env python3
"""Exercise exact-time target tracking through the public ROS topic interface."""

import json
import time

import rclpy
from rcl_interfaces.msg import Log
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from robot_interfaces.msg import Det, Dets
from sensor_msgs.msg import Image
from std_msgs.msg import Bool


class AcceptanceFailure(RuntimeError):
    pass


class ObjectTrackAcceptanceProbe(Node):
    def __init__(self):
        super().__init__("object_track_acceptance_probe")
        self.images = []
        self.previews = []
        self.status_logs = []
        sensor_qos = QoSProfile(depth=10)
        sensor_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        sensor_qos.durability = DurabilityPolicy.VOLATILE
        output_qos = QoSProfile(depth=10)
        output_qos.reliability = ReliabilityPolicy.RELIABLE
        output_qos.durability = DurabilityPolicy.VOLATILE
        log_qos = QoSProfile(depth=100)
        log_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        log_qos.durability = DurabilityPolicy.VOLATILE

        self.create_subscription(Image, "/camera/image_det_track", self.images.append, output_qos)
        self.create_subscription(Log, "/rosout", self._on_log, log_qos)
        fixture_qos = QoSProfile(depth=10)
        fixture_qos.reliability = ReliabilityPolicy.RELIABLE
        fixture_qos.durability = DurabilityPolicy.VOLATILE
        self.image_publisher = self.create_publisher(Image, "/camera/image_det", fixture_qos)
        self.detections_publisher = self.create_publisher(Dets, "/ai_msg_det", fixture_qos)
        self.enable_publisher = self.create_publisher(Bool, "/enable_tracking", 10)

    def _on_log(self, message):
        if message.name.endswith("object_track") and "dry-run preview" in message.msg:
            self.previews.append(message.msg)
        if message.name.endswith("object_track") and message.msg.startswith("tracking "):
            self.status_logs.append(message.msg)

    def spin_until(self, predicate, timeout, description):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if predicate():
                return
        raise AcceptanceFailure("timed out waiting for " + description)

    def publish_image(self, sec, nanosec):
        image = Image()
        image.header.stamp.sec = sec
        image.header.stamp.nanosec = nanosec
        image.header.frame_id = "camera_optical_frame"
        image.height = 720
        image.width = 1280
        image.encoding = "rgb8"
        image.is_bigendian = False
        image.step = image.width * 3
        image.data = bytes(image.step * image.height)
        self.image_publisher.publish(image)

    def publish_detections(self, sec, nanosec, boxes=None):
        detections = Dets()
        detections.header.stamp.sec = sec
        detections.header.stamp.nanosec = nanosec
        detections.image_width = 1280
        detections.image_height = 720
        if boxes is None:
            # 此框在 640×360 逻辑坐标中的面积最大，中心应产生 +1.7 rad/s。
            boxes = [(100, 100, 500, 700), (880, 100, 1200, 700)]
        for x1, y1, x2, y2 in boxes:
            person = Det()
            person.x1, person.y1, person.x2, person.y2 = x1, y1, x2, y2
            person.class_name = "person"
            detections.detections.append(person)
        self.detections_publisher.publish(detections)


def main():
    rclpy.init()
    node = ObjectTrackAcceptanceProbe()
    try:
        node.spin_until(
            lambda: node.image_publisher.get_subscription_count() > 0
            and node.detections_publisher.get_subscription_count() > 0
            and node.count_publishers("/camera/image_det_track") > 0
            and node.count_subscribers("/camera/image_det_track") > 0,
            5.0,
            "object_track input subscriptions",
        )
        discovery_deadline = time.monotonic() + 1.0
        while time.monotonic() < discovery_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)

        enabled = Bool()
        enabled.data = False
        node.enable_publisher.publish(enabled)
        node.spin_until(
            lambda: any("angular.z=0.000" in preview for preview in node.previews),
            3.0,
            "zero command preview after disabling tracking",
        )
        enabled.data = True
        node.enable_publisher.publish(enabled)
        node.spin_until(
            lambda: "tracking enabled" in node.status_logs,
            3.0,
            "tracking enable status",
        )
        node.images.clear()

        # 不同时间戳的输入必须不能生成跟踪输出。
        node.publish_image(51, 10)
        node.publish_detections(51, 11)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        if node.images:
            raise AcceptanceFailure("unmatched image and detections produced output")

        node.publish_detections(52, 20)
        node.publish_image(52, 20)
        node.spin_until(lambda: node.images, 10.0, "exact-time annotated image")
        node.spin_until(
            lambda: any("angular.z=1.700" in preview for preview in node.previews),
            10.0,
            "largest-person angular preview",
        )

        annotated = node.images[-1]
        if (annotated.header.stamp.sec, annotated.header.stamp.nanosec) != (52, 20):
            raise AcceptanceFailure("annotated output did not preserve the matched image timestamp")
        pixel = (100 * annotated.step) + (100 * 3)
        if tuple(annotated.data[pixel:pixel + 3]) != (255, 0, 0):
            raise AcceptanceFailure("selected person box was not drawn on the output image")
        status_pixels = sum(
            1
            for y in range(40)
            for x in range(500)
            if tuple(annotated.data[y * annotated.step + x * 3:y * annotated.step + x * 3 + 3])
            == (255, 0, 0)
        )
        if status_pixels == 0:
            raise AcceptanceFailure("tracking status text was not drawn on the output image")
        if node.count_publishers("/tracking/cmd_vel_safe") != 0:
            raise AcceptanceFailure("dry-run unexpectedly created a Twist publisher")

        # 验证靠近左边缘的目标会将角速度限制在 +3.0 rad/s。
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        node.publish_detections(53, 20, [(0, 100, 40, 700)])
        node.publish_image(53, 20)
        node.spin_until(
            lambda: any("angular.z=3.000" in preview for preview in node.previews),
            10.0,
            "bounded angular command preview",
        )

        # 等待日志节流窗口结束，再验证目标丢失会预览零角速度。
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        lost_detections = Dets()
        lost_detections.header.stamp.sec = 54
        lost_detections.header.stamp.nanosec = 21
        lost_detections.image_width = 1280
        lost_detections.image_height = 720
        node.detections_publisher.publish(lost_detections)
        node.publish_image(54, 21)
        node.spin_until(
            lambda: any("target lost" in preview and "angular.z=0.000" in preview
                        for preview in node.previews),
            10.0,
            "zero command preview after target loss",
        )

        node.publish_detections(55, 20)
        node.publish_image(55, 20)
        node.spin_until(
            lambda: sum("angular.z=1.700" in preview for preview in node.previews) >= 2,
            10.0,
            "tracking command after new target acquisition",
        )

        # 在已选择目标时禁用，必须立即预览零命令。
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        enabled.data = False
        node.enable_publisher.publish(enabled)
        node.spin_until(
            lambda: any("disabled" in preview and "angular.z=0.000" in preview
                        for preview in node.previews),
            10.0,
            "zero command preview when disabling an active target",
        )

        summary = {
            "annotated_stamp": [annotated.header.stamp.sec, annotated.header.stamp.nanosec],
            "preview": next(preview for preview in node.previews if "angular.z=1.700" in preview),
            "selected_box_outline_rgb": list(annotated.data[pixel:pixel + 3]),
            "acceptance": "PASS",
        }
        print(json.dumps(summary))
        return 0
    except AcceptanceFailure as error:
        print(json.dumps({"acceptance": "FAIL", "reason": str(error)}))
        return 2
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
