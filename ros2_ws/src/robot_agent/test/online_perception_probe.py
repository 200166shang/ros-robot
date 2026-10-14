"""用真实在线指令验收现有感知 Interface，凭证通过环境传入。"""

import json
import time
from typing import List, Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from robot_agent.online_ros_node import OnlineRosNode


def main(args: Optional[List[str]] = None) -> None:
    """固定 bringup 另行启动；验收不创建或管理感知进程。"""
    # 1. 连接真实 ROS 入口与在线 provider，观察公开结果与运动出口。
    rclpy.init(args=args)
    agent = OnlineRosNode()
    probe = Node("online_perception_acceptance_probe")
    executor = SingleThreadedExecutor()
    executor.add_node(agent)
    executor.add_node(probe)
    results = []
    motion = []
    scan_count = 0

    def receive_scan(message: LaserScan) -> None:
        """观察真实扫描到达，用于建立感知验收前提。"""
        nonlocal scan_count
        scan_count += 1

    def receive(message: String) -> None:
        """保存公开回执，不记录凭证或 provider 内部错误。"""
        results.append(json.loads(message.data))

    probe.create_subscription(String, "/online_agent/result", receive, 10)
    probe.create_subscription(
        Twist, "/tracking/cmd_vel_safe", motion.append, 10
    )
    probe.create_subscription(
        LaserScan, "/scan", receive_scan, qos_profile_sensor_data
    )
    publisher = probe.create_publisher(String, "/online_agent/text", 10)
    commands = [
        (
            "请恢复相机采集，只调用 start_receiving_image。",
            ["start_receiving_image"],
        ),
        ("请开启激光融合，只调用 enable_lidar。", ["enable_lidar"]),
        ("请启动跟随，只调用 start_following。", ["start_following"]),
        ("请查询跟随状态，只调用 following_status。", ["following_status"]),
        ("请关闭融合，只调用 disable_lidar。", ["disable_lidar"]),
        (
            "请暂停相机采集，只调用 stop_camera_collection。",
            ["stop_camera_collection"],
        ),
        (
            "请恢复相机采集，只调用 start_receiving_image。",
            ["start_receiving_image"],
        ),
        ("混合动作前先开启激光融合，只调用 enable_lidar。", ["enable_lidar"]),
        (
            "按顺序把音量设为35，启动跟随，查询音量，然后停止跟随。"
            "只依次调用 volume_set(35)、start_following、"
            "volume_status、stop_following。",
            [
                "volume_set",
                "start_following",
                "volume_status",
                "stop_following",
            ],
        ),
    ]
    try:
        # 2. 逐轮输入真实自然语言，等待模型选择及设备最终回执。
        deadline = time.monotonic() + 10
        while (
            publisher.get_subscription_count() == 0
            and time.monotonic() < deadline
        ):
            executor.spin_once(timeout_sec=0.05)
        assert publisher.get_subscription_count() > 0, "在线文本入口未发现"
        for text, expected in commands:
            count = len(results) + 1
            message = String()
            message.data = text
            publisher.publish(message)
            deadline = time.monotonic() + 75
            while len(results) < count and time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.05)
            assert len(results) == count, "在线回合未回复"
            result = results[-1]
            print(
                json.dumps(
                    {"input": text, "result": result}, ensure_ascii=False
                ),
                flush=True,
            )
            assert [a["name"] for a in result["actions"]] == expected, result
            assert result["status"] == "completed", result
            assert all(
                a["status"]
                == (
                    "simulated_success"
                    if a["name"].startswith("volume_")
                    else "real_success"
                )
                for a in result["actions"]
            ), result
            if expected == ["enable_lidar"]:
                # 融合回执只确认订阅开启；验收须另行确认真实扫描已到达。
                before = scan_count
                deadline = time.monotonic() + 5
                while scan_count < before + 2 and time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.05)
                assert scan_count >= before + 2, "融合开启后真实扫描未到达"
            if expected[0] == "volume_set":
                assert result["actions"][2]["data"]["level"] == 35, result
        # 3. dry-run 即使生成预览也不能向安全运动话题发布 Twist。
        assert motion == [], "dry-run 出现运动输出"
        print(
            "PASS: real online perception receipts; no Twist output",
            flush=True,
        )
    finally:
        agent.stop()
        executor.shutdown()
        agent.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
