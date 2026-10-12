#!/usr/bin/env python3
"""Exercise exact-time target tracking through the public ROS topic interface."""

import json
import time

import rclpy
from geometry_msgs.msg import TransformStamped
from rcl_interfaces.msg import Log
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from robot_interfaces.msg import Det, Dets
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import Bool
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster


class AcceptanceFailure(RuntimeError):
    pass


class ObjectTrackAcceptanceProbe(Node):
    def __init__(self):
        super().__init__("object_track_acceptance_probe")
        self.transform_broadcaster = StaticTransformBroadcaster(self)
        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = "camera"
        transform.child_frame_id = "laser_link"
        transform.transform.translation.x = 0.20
        transform.transform.rotation.x = 0.5
        transform.transform.rotation.y = -0.5
        transform.transform.rotation.z = 0.5
        transform.transform.rotation.w = 0.5
        self.transform_broadcaster.sendTransform(transform)
        self.images = []
        self.previews = []
        self.status_logs = []
        self.lidar_logs = []
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
        self.lidar_enable_publisher = self.create_publisher(Bool, "/enable_lidar", 10)
        self.scan_publisher = self.create_publisher(LaserScan, "/scan", sensor_qos)

    def _on_log(self, message):
        if message.name.endswith("object_track") and "dry-run preview" in message.msg:
            self.previews.append(message.msg)
        if message.name.endswith("object_track") and message.msg.startswith("tracking "):
            self.status_logs.append(message.msg)
        if message.name.endswith("object_track") and message.msg.startswith("lidar "):
            self.lidar_logs.append(message.msg)

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
        image.header.frame_id = "camera"
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

    def publish_scan_fixture(self):
        scan = LaserScan()
        scan.header.frame_id = "laser_link"
        scan.angle_min = 0.0
        scan.angle_increment = 1.0
        scan.range_min = 0.1
        scan.range_max = 10.0
        scan.ranges = [0.5]
        self.scan_publisher.publish(scan)

    def publish_pair_until(self, sec, nanosec, boxes, predicate, description, timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.publish_detections(sec, nanosec, boxes)
            self.publish_image(sec, nanosec)
            retry_deadline = min(deadline, time.monotonic() + 0.5)
            while time.monotonic() < retry_deadline:
                rclpy.spin_once(self, timeout_sec=0.05)
                if predicate():
                    return
        raise AcceptanceFailure("timed out waiting for " + description)


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

        node.publish_pair_until(
            52,
            20,
            None,
            lambda: any((image.header.stamp.sec, image.header.stamp.nanosec) == (52, 20)
                        for image in node.images)
            and any("angular.z=1.700" in preview for preview in node.previews),
            "exact-time annotated image and largest-person command",
        )

        annotated = node.images[-1]
        if (annotated.header.stamp.sec, annotated.header.stamp.nanosec) != (52, 20):
            raise AcceptanceFailure("annotated output did not preserve the matched image timestamp")
        pixel = (100 * annotated.step) + (100 * 3)
        if tuple(annotated.data[pixel:pixel + 3]) != (0, 255, 0):
            raise AcceptanceFailure("selected person box was not drawn on the output image")
        status_pixels = sum(
            1
            for y in range(40)
            for x in range(500)
            if tuple(annotated.data[y * annotated.step + x * 3:y * annotated.step + x * 3 + 3])
            == (0, 255, 0)
        )
        if status_pixels == 0:
            raise AcceptanceFailure("tracking status text was not drawn on the output image")
        if node.count_publishers("/tracking/cmd_vel_safe") != 0:
            raise AcceptanceFailure("dry-run unexpectedly created a Twist publisher")

        # 验证启用 LiDAR 后，扫描点会投影到图像并产生距离线速度预览。
        lidar_enabled = Bool()
        lidar_enabled.data = True
        node.lidar_enable_publisher.publish(lidar_enabled)
        node.spin_until(
            lambda: any(log == "lidar enabled" for log in node.lidar_logs)
            and node.count_subscribers("/scan") > 0,
            3.0,
            "LiDAR subscription enable",
        )
        projected_box = [(600, 100, 1270, 700)]
        node.images.clear()
        node.publish_pair_until(56, 19, projected_box, lambda: any(
            (image.header.stamp.sec, image.header.stamp.nanosec) == (56, 19) for image in node.images),
            "selected target box before scan update")
        node.publish_scan_fixture()
        node.publish_pair_until(
            56,
            20,
            projected_box,
            lambda: any("range=0.538516m" in preview and "linear.x=0.119" in preview
                        for preview in node.previews)
            and any((image.header.stamp.sec, image.header.stamp.nanosec) == (56, 20)
                    for image in node.images),
            "projected scan range and distance-follow preview",
        )
        projected = next(image for image in node.images
                         if (image.header.stamp.sec, image.header.stamp.nanosec) == (56, 20))
        projected_pixel = 360 * projected.step + 1204 * 3
        if tuple(projected.data[projected_pixel:projected_pixel + 3]) != (0, 255, 0):
            raise AcceptanceFailure("projected LiDAR point was not drawn on the tracking image")
        range_status_pixels = sum(
            1
            for y in range(40)
            for x in range(0, 900)
            if tuple(projected.data[y * projected.step + x * 3:y * projected.step + x * 3 + 3])
            == (0, 255, 0)
        )
        if range_status_pixels == 0:
            raise AcceptanceFailure("tracking image did not draw range and command status")

        # 禁用 LiDAR 后应移除订阅、清空点位和距离，并将线速度归零。
        lidar_enabled.data = False
        node.lidar_enable_publisher.publish(lidar_enabled)
        node.spin_until(
            lambda: any(log == "lidar disabled" for log in node.lidar_logs)
            and node.count_subscribers("/scan") == 0,
            3.0,
            "LiDAR subscription disable",
        )
        node.images.clear()
        node.publish_scan_fixture()
        node.publish_pair_until(
            57,
            20,
            projected_box,
            lambda: any("range=0.000000m" in preview and "linear.x=0.000" in preview
                        for preview in node.previews)
            and any((image.header.stamp.sec, image.header.stamp.nanosec) == (57, 20)
                    for image in node.images),
            "zero linear preview with LiDAR disabled",
        )
        cleared = next(image for image in node.images
                       if (image.header.stamp.sec, image.header.stamp.nanosec) == (57, 20))
        cleared_pixel = 360 * cleared.step + 1204 * 3
        if tuple(cleared.data[cleared_pixel:cleared_pixel + 3]) != (0, 0, 0):
            raise AcceptanceFailure("disabling LiDAR did not clear projected points")

        # 验证靠近左边缘的目标会将角速度限制在 +3.0 rad/s。
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        node.publish_pair_until(
            53,
            20,
            [(0, 100, 40, 700)],
            lambda: any("angular.z=3.000" in preview for preview in node.previews),
            "bounded angular command preview",
        )

        # 等待日志节流窗口结束，再验证目标丢失会预览零角速度。
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        node.publish_pair_until(
            54,
            21,
            [],
            lambda: any("no target found" in preview and "angular.z=0.000" in preview
                        for preview in node.previews),
            "zero command preview after target loss",
        )

        node.publish_pair_until(
            55,
            20,
            None,
            lambda: sum("angular.z=1.700" in preview for preview in node.previews) >= 2,
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
            "preview": next(preview for preview in node.previews if "range=0.538516m" in preview),
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
