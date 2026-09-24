#!/usr/bin/env python3
import json
import time

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import Log
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from robot_interfaces.msg import Det, Dets
from std_msgs.msg import String


def main():
    rclpy.init()
    node = Node('acceptance_probe')
    responses = []
    velocities = []
    previews = []
    response_sub = node.create_subscription(
        String, '/agent/response', lambda message: responses.append(message.data), 10)
    velocity_sub = node.create_subscription(
        Twist, '/tracking/cmd_vel_safe',
        lambda message: velocities.append((message.linear.x, message.angular.z)), 10)

    def collect_preview(message):
        if message.name == 'object_track' and 'dry-run preview' in message.msg:
            previews.append(message.msg)

    preview_sub = node.create_subscription(Log, '/rosout', collect_preview, 10)
    command_pub = node.create_publisher(String, '/agent/command', 10)
    sensor_qos = QoSProfile(depth=1)
    sensor_qos.reliability = ReliabilityPolicy.BEST_EFFORT
    sensor_qos.durability = DurabilityPolicy.VOLATILE
    detection_pub = node.create_publisher(Dets, '/ai_msg_det', sensor_qos)

    start = time.monotonic()
    sent = False
    preview_seen_at = None
    while time.monotonic() - start < 12.0:
        if time.monotonic() - start > 3.0 and not sent:
            command = String()
            command.data = 'start_tracking'
            command_pub.publish(command)
            sent = True
        if sent and responses:
            detections = Dets()
            detections.image_width = 1280
            detections.image_height = 720
            person = Det()
            person.x1 = 80
            person.y1 = 100
            person.x2 = 480
            person.y2 = 700
            person.class_name = 'person'
            person.confidence = 0.95
            detections.detections.append(person)
            detection_pub.publish(detections)
        rclpy.spin_once(node, timeout_sec=0.1)
        if previews and preview_seen_at is None:
            preview_seen_at = time.monotonic()
        if responses and preview_seen_at is not None and time.monotonic() - preview_seen_at >= 1.0:
            break

    print('responses=' + json.dumps(responses))
    print('dry_run_previews=' + json.dumps(previews[:5]))
    print('motion_topic_messages=' + json.dumps(velocities[:5]))
    safe = bool(responses) and bool(previews) and not velocities
    print('acceptance=' + ('PASS' if safe else 'FAIL'))
    del response_sub, velocity_sub, preview_sub
    node.destroy_node()
    rclpy.shutdown()
    return 0 if safe else 2


if __name__ == '__main__':
    raise SystemExit(main())
