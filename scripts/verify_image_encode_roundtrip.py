#!/usr/bin/env python3
"""Verify the ROS image -> JPEG encoder -> ROS JPEG decoder topic path."""

import argparse
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, Image


class RoundTripProbe(Node):
    """Publish a color fixture and validate the encoder and decoder outputs."""

    def __init__(self):
        super().__init__("image_encode_roundtrip_probe")
        qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.publisher = self.create_publisher(Image, "/camera/image_raw", qos)
        self.compressed = None
        self.decoded = None
        self.create_subscription(
            CompressedImage,
            "/camera/image_raw/compressed",
            self.on_compressed,
            qos,
        )
        self.create_subscription(Image, "/roundtrip/image", self.on_decoded, qos)
        self.message = self.make_image()
        self.timer = self.create_timer(0.5, lambda: self.publisher.publish(self.message))

    @staticmethod
    def make_image():
        image = Image()
        image.header.stamp.sec = 123
        image.header.stamp.nanosec = 456789
        image.header.frame_id = "camera_roundtrip"
        image.height = 360
        image.width = 640
        image.encoding = "rgb8"
        image.is_bigendian = False
        image.step = image.width * 3
        rows = [
            bytes([240, 20, 20]) * 320 + bytes([20, 230, 30]) * 320
        ] * 180
        rows += [
            bytes([30, 40, 240]) * 320 + bytes([230, 220, 20]) * 320
        ] * 180
        image.data = b"".join(rows)
        return image

    def on_compressed(self, message):
        self.compressed = message

    def on_decoded(self, message):
        self.decoded = message


def validate_roundtrip(probe):
    compressed = probe.compressed
    decoded = probe.decoded
    if compressed.header != probe.message.header:
        raise RuntimeError("encoder changed the input header")
    if compressed.format != "jpeg" or bytes(compressed.data[:2]) != b"\xff\xd8":
        raise RuntimeError("encoder output is not a JPEG with format 'jpeg'")
    if decoded.header != probe.message.header:
        raise RuntimeError("decoder changed the input header")
    if decoded.encoding != "rgb8":
        raise RuntimeError(f"unexpected decoded encoding: {decoded.encoding!r}")
    if (decoded.width, decoded.height) != (320, 180):
        raise RuntimeError(
            f"unexpected decoded dimensions: {decoded.width}x{decoded.height}"
        )

    samples = (
        (80, 45, (240, 20, 20)),
        (240, 45, (20, 230, 30)),
        (80, 135, (30, 40, 240)),
        (240, 135, (230, 220, 20)),
    )
    for x, y, expected in samples:
        offset = y * decoded.step + x * 3
        actual = tuple(decoded.data[offset : offset + 3])
        if any(abs(int(got) - want) > 50 for got, want in zip(actual, expected)):
            raise RuntimeError(
                f"pixel at ({x},{y}) expected near {expected}, got {actual}"
            )

    print(
        f"PASS format={compressed.format} jpeg_bytes={len(compressed.data)} "
        f"header={decoded.header.frame_id}@{decoded.header.stamp.sec}."
        f"{decoded.header.stamp.nanosec} image={decoded.width}x{decoded.height} "
        "rgb8 quadrants=PASS"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout-seconds", type=float, default=15.0,
        help="maximum time to receive the encoder and decoder output",
    )
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    rclpy.init()
    probe = RoundTripProbe()
    deadline = time.monotonic() + args.timeout_seconds
    try:
        while time.monotonic() < deadline:
            if probe.compressed is not None and probe.decoded is not None:
                validate_roundtrip(probe)
                return
            rclpy.spin_once(probe, timeout_sec=0.1)
        raise RuntimeError("timed out waiting for encoder and ROS decoder output")
    finally:
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
