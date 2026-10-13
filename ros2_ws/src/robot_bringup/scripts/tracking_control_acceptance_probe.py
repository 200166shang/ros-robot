#!/usr/bin/env python3
"""通过公开 ROS 控制接口验证单一跟踪组合的安全行为。"""

import time
from typing import Any, Callable, List, Sequence, Tuple

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import Log
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from robot_interfaces.msg import Det, Dets
from sensor_msgs.msg import Image, LaserScan
from std_srvs.srv import SetBool


Box = Tuple[int, int, int, int]


class AcceptanceFailure(RuntimeError):
    """表示公开 ROS 接口验收未达到预期。"""
    pass


class TrackingControlAcceptanceProbe(Node):
    """通过 ROS topic 和 service 验收 LiDAR 融合与 Follow 控制。"""

    def __init__(self) -> None:
        super().__init__("tracking_control_acceptance_probe")
        self._sequence: int = 1
        self._annotations: List[Image] = []
        self._previews: List[str] = []

        output_qos = QoSProfile(depth=10)
        output_qos.reliability = ReliabilityPolicy.RELIABLE
        output_qos.durability = DurabilityPolicy.VOLATILE
        log_qos = QoSProfile(depth=100)
        log_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        log_qos.durability = DurabilityPolicy.VOLATILE
        fixture_qos = QoSProfile(depth=10)
        fixture_qos.reliability = ReliabilityPolicy.RELIABLE
        fixture_qos.durability = DurabilityPolicy.VOLATILE
        sensor_qos = QoSProfile(depth=10)
        sensor_qos.reliability = ReliabilityPolicy.BEST_EFFORT
        sensor_qos.durability = DurabilityPolicy.VOLATILE

        self.annotation_subscription = self.create_subscription(
            Image, "/camera/image_det_track", self._annotations.append, output_qos
        )
        self.create_subscription(Log, "/rosout", self._on_log, log_qos)
        self.create_subscription(
            Twist, "/tracking/cmd_vel_safe", lambda _message: None, 10
        )
        self.image_publisher = self.create_publisher(
            Image, "/camera/image_det", fixture_qos
        )
        self.detections_publisher = self.create_publisher(
            Dets, "/ai_msg_det", fixture_qos
        )
        self.scan_publisher = self.create_publisher(LaserScan, "/scan", sensor_qos)
        self.enable_client = self.create_client(SetBool, "/tracking/set_enabled")
        self.lidar_client = self.create_client(
            SetBool, "/tracking/set_lidar_enabled"
        )

    def _on_log(self, message: Log) -> None:
        if message.name.endswith("object_track") and "dry-run preview" in message.msg:
            self._previews.append(message.msg)

    def spin_until(
        self,
        predicate: Callable[[], bool],
        timeout: float,
        description: str,
    ) -> None:
        """持续处理 ROS 回调，直到条件满足或等待超时。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.05)
            if predicate():
                return
        raise AcceptanceFailure("timed out waiting for " + description)

    def call_set_bool(self, client: Any, enabled: bool) -> SetBool.Response:
        """调用 SetBool 服务并等待其响应。"""
        request = SetBool.Request()
        request.data = enabled
        future = client.call_async(request)
        self.spin_until(future.done, 3.0, "SetBool service response")
        response = future.result()
        if response is None:
            raise AcceptanceFailure("SetBool service returned no response")
        return response

    def publish_scan_fixture(self) -> None:
        """发布一帧雷达样例，供本地隔离验收使用。"""
        scan = LaserScan()
        scan.header.frame_id = "laser_link"
        scan.angle_increment = 1.0
        scan.range_min = 0.1
        scan.range_max = 10.0
        scan.ranges = [0.5]
        self.scan_publisher.publish(scan)

    def enable_follow_with_fresh_scan(self, timeout: float = 5.0) -> SetBool.Response:
        """刷新扫描并重试，直到 Follow 就绪或返回其他拒绝原因。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.publish_scan_fixture()
            rclpy.spin_once(self, timeout_sec=0.05)
            response = self.call_set_bool(self.enable_client, True)
            if response.success or "recent LaserScan" not in response.message:
                return response
        raise AcceptanceFailure(
            "Follow enable kept rejecting fresh LaserScan fixtures"
        )

    def publish_pair(
        self,
        boxes: Sequence[Box],
        wait_for_annotation: bool = True,
    ) -> None:
        """发布同步图像与检测框，并可等待 tracker 的标注图像。"""
        if wait_for_annotation:
            before = len(self._annotations)
            deadline = time.monotonic() + 10.0

        while True:
            sequence = self._sequence
            self._sequence += 1
            image = Image()
            image.header.stamp.sec = 100 + sequence // 1_000_000_000
            image.header.stamp.nanosec = sequence
            image.header.frame_id = "camera"
            image.height = 720
            image.width = 1280
            image.encoding = "rgb8"
            image.step = image.width * 3
            image.data = bytes(image.step * image.height)

            detections = Dets()
            detections.header = image.header
            detections.image_width = image.width
            detections.image_height = image.height
            for x1, y1, x2, y2 in boxes:
                detection = Det()
                detection.x1 = x1
                detection.y1 = y1
                detection.x2 = x2
                detection.y2 = y2
                detection.class_name = "person"
                detections.detections.append(detection)

            self.publish_scan_fixture()
            self.image_publisher.publish(image)
            self.detections_publisher.publish(detections)
            if not wait_for_annotation:
                return

            retry_deadline = min(deadline, time.monotonic() + 0.25)
            while time.monotonic() < retry_deadline:
                rclpy.spin_once(self, timeout_sec=0.05)
                if len(self._annotations) > before:
                    return
            if time.monotonic() >= deadline:
                raise AcceptanceFailure(
                    'timed out waiting for tracking-annotated image '
                    'for synchronized inputs'
                )

    def publish_until_preview(
        self,
        boxes: Sequence[Box],
        expected: str,
        timeout: float,
        wait_for_annotation: bool = True,
    ) -> str:
        """重复发布检测结果，直到 dry-run 指令包含预期片段。"""
        previous_previews = len(self._previews)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.publish_pair(boxes, wait_for_annotation=wait_for_annotation)
            retry_deadline = min(deadline, time.monotonic() + 0.2)
            while time.monotonic() < retry_deadline:
                rclpy.spin_once(self, timeout_sec=0.05)
                matching_preview = any(
                    expected in preview
                    for preview in self._previews[previous_previews:]
                )
                if matching_preview:
                    return self._previews[-1]
        raise AcceptanceFailure(
            'timed out waiting for dry-run preview containing ' + expected
        )


def main() -> None:
    """运行公开 ROS 控制接口的跟踪与 LiDAR 安全验收场景。"""
    rclpy.init()
    node = TrackingControlAcceptanceProbe()
    try:
        node.spin_until(
            lambda: node.enable_client.service_is_ready()
            and node.lidar_client.service_is_ready(),
            10.0,
            "tracking control services",
        )
        node.spin_until(
            lambda: node.image_publisher.get_subscription_count() > 0
            and node.detections_publisher.get_subscription_count() > 0,
            5.0,
            "tracker input subscriptions",
        )

        refused = node.call_set_bool(node.enable_client, True)
        if refused.success or "input" not in refused.message.lower():
            raise AcceptanceFailure(
                'Follow enable should be refused before synchronized input; '
                'received {!r}'.format(refused)
            )

        if node.count_subscribers("/scan") != 0:
            raise AcceptanceFailure("LiDAR Fusion should be disabled at startup")

        # 输入就绪但融合关闭时必须拒绝 Follow，且不生成预览命令。
        previews_before_input = len(node._previews)
        node.publish_pair([])
        if len(node._previews) != previews_before_input:
            raise AcceptanceFailure(
                "Follow should remain in standby before its service is enabled"
            )
        refused_without_lidar = node.call_set_bool(node.enable_client, True)
        if (
            refused_without_lidar.success
            or "lidar fusion" not in refused_without_lidar.message.lower()
        ):
            raise AcceptanceFailure(
                "Follow enable should require LiDAR Fusion: "
                + refused_without_lidar.message
            )

        lidar_enabled = node.call_set_bool(node.lidar_client, True)
        if not lidar_enabled.success:
            raise AcceptanceFailure(
                "LiDAR Fusion enable was rejected: " + lidar_enabled.message
            )
        node.spin_until(
            lambda: node.count_subscribers("/scan") > 0,
            3.0,
            "ObjectTrack LiDAR subscription",
        )

        # 输入先到达并发布标注；standby 状态可在没有目标时启用。
        previews_before_input = len(node._previews)
        node.publish_pair([])
        if len(node._previews) != previews_before_input:
            raise AcceptanceFailure(
                "Follow should remain in standby before its service is enabled"
            )
        enabled = node.enable_follow_with_fresh_scan()
        if not enabled.success:
            raise AcceptanceFailure("Follow enable was rejected: " + enabled.message)

        # 无目标时保持 Follow 并输出零命令；检测到人物后恢复跟随。
        no_target_preview = node.publish_until_preview(
            [], "no target found", 2.5
        )
        if (
            "linear.x=0.000" not in no_target_preview
            or "angular.z=0.000" not in no_target_preview
        ):
            raise AcceptanceFailure(
                'no-person command was not zero: ' + no_target_preview
            )

        target_preview = node.publish_until_preview(
            [(780, 80, 1220, 640)],
            "linear.x=0.119",
            10.0,
            wait_for_annotation=False,
        )
        if "angular.z=-1.800" not in target_preview:
            raise AcceptanceFailure(
                "LiDAR-backed target did not preserve the expected turn command: "
                + target_preview
            )

        # 移除观察者订阅后继续输入，Follow 命令仍应产生。
        node.destroy_subscription(node.annotation_subscription)
        node.publish_until_preview(
            [(0, 80, 200, 520)],
            "angular.z=2.700",
            2.5,
            wait_for_annotation=False,
        )

        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        paused = node.call_set_bool(node.enable_client, False)
        if not paused.success:
            raise AcceptanceFailure("Follow pause was rejected: " + paused.message)
        node.spin_until(
            lambda: any(
                "disabled" in preview
                and "linear.x=0.000" in preview
                and "angular.z=0.000" in preview
                for preview in node._previews
            ),
            3.0,
            "zero command after disabling Follow",
        )

        resumed = node.enable_follow_with_fresh_scan()
        if not resumed.success:
            raise AcceptanceFailure(
                "Follow could not be re-enabled: " + resumed.message
            )
        preview_deadline = time.monotonic() + 1.1
        while time.monotonic() < preview_deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        lidar_disabled = node.call_set_bool(node.lidar_client, False)
        if not lidar_disabled.success:
            raise AcceptanceFailure("LiDAR Fusion disable was rejected")
        node.spin_until(
            lambda: node.count_subscribers("/scan") == 0
            and any(
                "LiDAR fusion disabled" in preview
                and "linear.x=0.000" in preview
                and "angular.z=0.000" in preview
                for preview in node._previews
            ),
            3.0,
            "LiDAR subscription cleanup and Follow stop",
        )
        refused_without_lidar = node.call_set_bool(node.enable_client, True)
        if (
            refused_without_lidar.success
            or "lidar fusion" not in refused_without_lidar.message.lower()
        ):
            raise AcceptanceFailure(
                "Follow should be refused when LiDAR Fusion is disabled"
            )

        if node.count_publishers("/tracking/cmd_vel_safe") != 0:
            raise AcceptanceFailure("dry-run created a Twist publisher")
        if node.count_subscribers("/scan") != 0:
            raise AcceptanceFailure(
                "ObjectTrack remained subscribed to /scan with LiDAR Fusion disabled"
            )

        print("tracking_control=passed")
        print("lidar_fusion_and_follow_services=passed")
        print("range_gated_forward_output=passed")
        print("follow_standby_and_safe_stop=passed")
        print("observation_disconnect=passed")
        print("scan_subscription_lifecycle=passed")
        print("dry_run=true")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
