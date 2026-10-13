#!/usr/bin/env python3
"""通过公开 ROS Topic 验证时间戳精确同步的目标跟踪行为。"""

import json
import time
from threading import Event, Thread

import rclpy
from geometry_msgs.msg import TransformStamped, Twist
from rcl_interfaces.msg import Log
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from robot_interfaces.msg import Det, Dets
from sensor_msgs.msg import Image, LaserScan
from std_srvs.srv import SetBool
from tf2_ros import StaticTransformBroadcaster


class AcceptanceFailure(RuntimeError):
    pass


class ObjectTrackAcceptanceProbe(Node):
    def __init__(self):
        super().__init__("object_track_acceptance_probe")
        self.images = []
        self.previews = []
        self.status_logs = []
        self.command_messages = []
        sensor_qos = QoSProfile(depth=10)
        sensor_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        sensor_qos.durability = DurabilityPolicy.VOLATILE
        output_qos = QoSProfile(depth=10)
        output_qos.reliability = ReliabilityPolicy.RELIABLE
        output_qos.durability = DurabilityPolicy.VOLATILE
        log_qos = QoSProfile(depth=100)
        log_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        log_qos.durability = DurabilityPolicy.VOLATILE

        self.create_subscription(
            Image, "/camera/image_det_track", self.images.append, output_qos
        )
        self.create_subscription(
            Twist, "/tracking/cmd_vel_safe", self.command_messages.append, 10
        )
        self.create_subscription(Log, "/rosout", self._on_log, log_qos)
        fixture_qos = QoSProfile(depth=10)
        fixture_qos.reliability = ReliabilityPolicy.RELIABLE
        fixture_qos.durability = DurabilityPolicy.VOLATILE
        self.image_publisher = self.create_publisher(
            Image, "/camera/image_det", fixture_qos
        )
        self.detections_publisher = self.create_publisher(
            Dets, "/ai_msg_det", fixture_qos
        )
        self.enable_client = self.create_client(SetBool, "/tracking/set_enabled")
        self.lidar_enable_client = self.create_client(
            SetBool,
            "/tracking/set_lidar_enabled",
        )
        self.scan_publisher = self.create_publisher(LaserScan, "/scan", sensor_qos)
        self.transform_broadcaster = StaticTransformBroadcaster(self)
        self._stop_scan_stream = Event()
        self._scan_stream_thread = None

    def _on_log(self, message):
        if message.name.endswith("object_track") and "dry-run preview" in message.msg:
            self.previews.append(message.msg)
        if (
            message.name.endswith("object_track")
            and message.msg.startswith("tracking ")
        ):
            self.status_logs.append(message.msg)

    def spin_until(self, predicate, timeout, description):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if predicate():
                return
        raise AcceptanceFailure("timed out waiting for " + description)

    def call_set_bool(self, client, enabled):
        """调用 SetBool 服务并返回完成后的响应。"""
        request = SetBool.Request()
        request.data = enabled
        future = client.call_async(request)
        self.spin_until(future.done, 3.0, "SetBool service response")
        response = future.result()
        if response is None:
            raise AcceptanceFailure("SetBool service returned no response")
        return response

    def enable_follow_with_fresh_scan(self, timeout=5.0):
        """仅在服务拒绝过期扫描时刷新样例并重试启用 Follow。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # 仅在服务报告扫描过期时刷新，避免大图处理时误判数据失效。
            self.publish_scan_fixture()
            rclpy.spin_once(self, timeout_sec=0.05)
            response = self.call_set_bool(self.enable_client, True)
            if response.success or "recent LaserScan" not in response.message:
                return response
        raise AcceptanceFailure("Follow enable kept rejecting fresh LaserScan fixtures")

    def enable_lidar_after_transform(self, timeout=5.0):
        """发布平台外参测试 TF，再启用 LiDAR Fusion。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.call_set_bool(self.lidar_enable_client, True)
            if response.success or "camera <- laser TF" not in response.message:
                return response
            self.publish_tracking_transform()
            rclpy.spin_once(self, timeout_sec=0.05)
            time.sleep(0.1)
        raise AcceptanceFailure("LiDAR Fusion kept waiting for the test transform")

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
            # 两框中较大的目标中心对应 +1.7 rad/s。
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

    def publish_tracking_transform(self):
        """发布与平台配置一致的 camera 到 laser_link 测试变换。"""
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

    def start_scan_fixture_stream(self):
        """处理大图样例期间持续发布扫描数据。"""
        self._stop_scan_stream.clear()

        def publish_scans():
            while not self._stop_scan_stream.is_set():
                self.publish_scan_fixture()
                self._stop_scan_stream.wait(0.1)

        self._scan_stream_thread = Thread(target=publish_scans, daemon=True)
        self._scan_stream_thread.start()

    def stop_scan_fixture_stream(self):
        """销毁节点前停止并等待后台扫描发布线程。"""
        self._stop_scan_stream.set()
        if self._scan_stream_thread is not None:
            self._scan_stream_thread.join(timeout=1.0)

    def publish_pair_until(
        self,
        sec,
        nanosec,
        boxes,
        predicate,
        description,
        timeout=10.0,
        publish_scan=True,
    ):
        """重复发布同步图像样例，直到收到预期输出。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if publish_scan:
                self.publish_scan_fixture()
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
            lambda: node.enable_client.service_is_ready()
            and node.lidar_enable_client.service_is_ready()
            and node.image_publisher.get_subscription_count() > 0
            and node.detections_publisher.get_subscription_count() > 0
            and node.count_publishers("/camera/image_det_track") > 0
            and node.count_subscribers("/camera/image_det_track") > 0,
            5.0,
            "object_track services and input subscriptions",
        )
        discovery_deadline = time.monotonic() + 1.0
        while time.monotonic() < discovery_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)

        refused = node.call_set_bool(node.enable_client, True)
        if refused.success or "input" not in refused.message.lower():
            raise AcceptanceFailure(
                "Follow enable should wait for synchronized inputs: "
                + refused.message
            )

        refused_without_tf = node.call_set_bool(node.lidar_enable_client, True)
        if (
            refused_without_tf.success
            or "camera <- laser TF" not in refused_without_tf.message
        ):
            raise AcceptanceFailure(
                "LiDAR Fusion should wait for camera <- laser TF: "
                + refused_without_tf.message
            )
        lidar_enabled = node.enable_lidar_after_transform()
        if not lidar_enabled.success:
            raise AcceptanceFailure(
                "LiDAR fusion could not be enabled: " + lidar_enabled.message
            )
        node.spin_until(
            lambda: node.count_subscribers("/scan") > 0,
            3.0,
            "LiDAR scan subscription",
        )
        node.start_scan_fixture_stream()
        node.publish_pair_until(
            50,
            10,
            [],
            lambda: any(
                (image.header.stamp.sec, image.header.stamp.nanosec) == (50, 10)
                for image in node.images
            ),
            "initial synchronized input and fresh LaserScan",
        )
        node.stop_scan_fixture_stream()
        time.sleep(1.1)
        refused_with_stale_scan = node.call_set_bool(node.enable_client, True)
        if (
            refused_with_stale_scan.success
            or "recent LaserScan" not in refused_with_stale_scan.message
        ):
            raise AcceptanceFailure(
                "Follow should wait for a fresh LaserScan: "
                + refused_with_stale_scan.message
            )
        node.start_scan_fixture_stream()
        enabled = node.enable_follow_with_fresh_scan()
        if not enabled.success:
            raise AcceptanceFailure("Follow enable was rejected: " + enabled.message)
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
            lambda: any(
                (image.header.stamp.sec, image.header.stamp.nanosec) == (52, 20)
                for image in node.images
            )
            and any(
                "angular.z=1.700" in preview for preview in node.previews
            ),
            "exact-time annotated image and largest-person command",
        )

        annotated = node.images[-1]
        if (annotated.header.stamp.sec, annotated.header.stamp.nanosec) != (52, 20):
            raise AcceptanceFailure(
                "annotated output did not preserve the matched image timestamp"
            )
        pixel = (100 * annotated.step) + (100 * 3)
        if tuple(annotated.data[pixel:pixel + 3]) != (0, 255, 0):
            raise AcceptanceFailure(
                "selected person box was not drawn on the output image"
            )
        status_pixels = sum(
            1
            for y in range(40)
            for x in range(500)
            if tuple(
                annotated.data[
                    y * annotated.step + x * 3:y * annotated.step + x * 3 + 3
                ]
            ) == (0, 255, 0)
        )
        if status_pixels == 0:
            raise AcceptanceFailure(
                "tracking status text was not drawn on the output image"
            )
        if node.count_publishers("/tracking/cmd_vel_safe") != 0:
            raise AcceptanceFailure("dry-run unexpectedly created a Twist publisher")

        # 扫描点投影到目标框后应产生由距离决定的线速度预览。
        projected_box = [(600, 100, 1270, 700)]
        node.images.clear()
        node.publish_pair_until(
            56,
            19,
            projected_box,
            lambda: any(
                (image.header.stamp.sec, image.header.stamp.nanosec) == (56, 19)
                for image in node.images
            ),
            "selected target box before scan update",
        )
        node.publish_scan_fixture()
        node.publish_pair_until(
            56,
            20,
            projected_box,
            lambda: any(
                "range=0.538516m" in preview and "linear.x=0.119" in preview
                for preview in node.previews
            )
            and any(
                (image.header.stamp.sec, image.header.stamp.nanosec) == (56, 20)
                for image in node.images
            ),
            "projected scan range and distance-follow preview",
        )
        projected = next(
            image
            for image in node.images
            if (image.header.stamp.sec, image.header.stamp.nanosec) == (56, 20)
        )
        projected_pixel = 360 * projected.step + 1204 * 3
        if tuple(projected.data[projected_pixel:projected_pixel + 3]) != (0, 255, 0):
            raise AcceptanceFailure(
                "projected LiDAR point was not drawn on the tracking image"
            )
        range_status_pixels = sum(
            1
            for y in range(40)
            for x in range(0, 900)
            if tuple(
                projected.data[
                    y * projected.step + x * 3:y * projected.step + x * 3 + 3
                ]
            ) == (0, 255, 0)
        )
        if range_status_pixels == 0:
            raise AcceptanceFailure(
                "tracking image did not draw range and command status"
            )

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

        # 保持扫描新鲜并等待预览日志节流窗口结束，使后续超时停止可被探针观察。
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        node.stop_scan_fixture_stream()
        previews_before_stale_scan = len(node.previews)
        node.spin_until(
            lambda: any(
                "tracking waiting for LiDAR range" in preview
                and "linear.x=0.000" in preview
                and "angular.z=0.000" in preview
                for preview in node.previews[previews_before_stale_scan:]
            ),
            3.0,
            "zero command after the active scan expires without a camera frame",
        )
        node.start_scan_fixture_stream()

        # 在已选择目标时禁用，必须立即预览零命令。
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        disabled = node.call_set_bool(node.enable_client, False)
        if not disabled.success:
            raise AcceptanceFailure("Follow pause was rejected: " + disabled.message)
        node.spin_until(
            lambda: any("disabled" in preview and "angular.z=0.000" in preview
                        for preview in node.previews),
            10.0,
            "zero command preview when disabling an active target",
        )

        resumed = node.enable_follow_with_fresh_scan()
        if not resumed.success:
            raise AcceptanceFailure(
                "Follow could not be re-enabled: " + resumed.message
            )
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        lidar_disabled = node.call_set_bool(node.lidar_enable_client, False)
        if not lidar_disabled.success:
            raise AcceptanceFailure("LiDAR fusion could not be disabled")
        node.spin_until(
            lambda: node.count_subscribers("/scan") == 0
            and any(
                "LiDAR fusion disabled" in preview
                and "linear.x=0.000" in preview
                and "angular.z=0.000" in preview
                for preview in node.previews
            ),
            3.0,
            "LiDAR subscription cleanup and automatic Follow stop",
        )
        refused_without_lidar = node.call_set_bool(node.enable_client, True)
        if (
            refused_without_lidar.success
            or "lidar fusion" not in refused_without_lidar.message.lower()
        ):
            raise AcceptanceFailure(
                "Follow must be refused when LiDAR fusion is disabled"
            )

        command_observation_deadline = time.monotonic() + 0.5
        while time.monotonic() < command_observation_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)

        if node.command_messages:
            raise AcceptanceFailure(
                "dry-run published Twist messages on /tracking/cmd_vel_safe"
            )

        summary = {
            "annotated_stamp": [
                annotated.header.stamp.sec,
                annotated.header.stamp.nanosec,
            ],
            "preview": next(
                preview
                for preview in node.previews
                if "range=0.538516m" in preview
            ),
            "selected_box_outline_rgb": list(annotated.data[pixel:pixel + 3]),
            "acceptance": "PASS",
        }
        print(json.dumps(summary))
        return 0
    except AcceptanceFailure as error:
        print(json.dumps({"acceptance": "FAIL", "reason": str(error)}))
        return 2
    finally:
        node.stop_scan_fixture_stream()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
