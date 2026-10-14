"""通过统一启动的公开话题验收真实在线、实机感知和重启记忆。"""

import argparse
import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import ParameterType
from rcl_interfaces.srv import GetParameters
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import String


class OnlineIntegrationProbe(Node):
    """只观察已启动的入口，不创建 provider 或管理感知进程。"""

    def __init__(self) -> None:
        """记录公开回执、真实传感器数据和两个运动出口。"""
        super().__init__("online_integration_probe")
        self.results: List[Dict] = []
        self.motion: List[Twist] = []
        self.scans = 0
        self.images = 0
        self.create_subscription(
            String, "/online_agent/result", self._receive, 10
        )
        for topic in ("/cmd_vel", "/tracking/cmd_vel_safe"):
            self.create_subscription(Twist, topic, self.motion.append, 10)
        self.create_subscription(
            LaserScan, "/scan", self._scan, qos_profile_sensor_data
        )
        self.create_subscription(
            Image, "/camera/image_det", self._image, qos_profile_sensor_data
        )

    def _receive(self, message: String) -> None:
        """解析在线入口的外部回执，保留识别文本及动作事实。"""
        self.results.append(json.loads(message.data))

    def _scan(self, message: LaserScan) -> None:
        """累计真实雷达输入，不使用固定扫描替代。"""
        self.scans += 1

    def _image(self, message: Image) -> None:
        """累计实际检测标注图像，作为 Follow 输入前提证据。"""
        self.images += 1

    def wait(
        self, predicate: Callable[[], bool], timeout: float, description: str
    ) -> None:
        """有界处理回调，验收条件未满足时直接失败。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)
            if predicate():
                return
        raise AssertionError(description)

    def confirm_dry_run(self, name: str) -> None:
        """读取实际节点参数，不能用入口意图代替设备安全确认。"""
        client = self.create_client(GetParameters, name + "/get_parameters")
        self.wait(client.service_is_ready, 15, "安全参数服务未发现")
        request = GetParameters.Request()
        request.names = ["dry_run"]
        future = client.call_async(request)
        self.wait(future.done, 5, "安全参数未回复")
        response = future.result()
        assert response is not None, "安全参数未返回回执"
        values = response.values
        assert len(values) == 1
        assert values[0].type == ParameterType.PARAMETER_BOOL
        assert values[0].bool_value is True
        self.destroy_client(client)

    def submit(
        self, topic: str, text: str, expected: Optional[List[str]] = None
    ) -> Dict:
        """真实输入等待完整在线回复，失败不重试，不替换模型选择。"""
        publisher = self.create_publisher(String, topic, 10)
        self.wait(
            lambda: publisher.get_subscription_count() == 1,
            15,
            "必须且仅能发现一个在线入口",
        )
        before = len(self.results)
        message = String()
        message.data = text
        publisher.publish(message)
        self.wait(lambda: len(self.results) > before, 180, "在线回合未回复")
        self.destroy_publisher(publisher)
        result = self.results[-1]
        print(json.dumps(result, ensure_ascii=False), flush=True)
        assert result["status"] == "completed", result
        if topic != "/online_agent/clear_memory":
            assert result["tts_status"] == "completed", result
            assert result["record_status"] == "completed", result
            assert not result.get("memory_warnings"), result
        if expected is not None:
            assert [a["name"] for a in result["actions"]] == expected, result
            for action in result["actions"]:
                status = (
                    "simulated_success"
                    if action["name"].startswith(("volume_", "head_"))
                    else "real_success"
                )
                assert action["status"] == status, result
        assert not self.motion, "dry-run 出现运动输出"
        return result


def main() -> None:
    """运行综合或重启阶段；原始回执和计数保存到源码外指定目录。"""
    parser = argparse.ArgumentParser(description="真实在线综合验收")
    parser.add_argument("--wav", required=True)
    parser.add_argument("--evidence-dir", required=True)
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--recall", action="store_true")
    phase.add_argument("--recording-only", action="store_true")
    args = parser.parse_args()
    rclpy.init()
    probe = OnlineIntegrationProbe()
    passed = False
    try:
        # 1. 确认统一入口及实际 tracker 的安全参数。
        probe.confirm_dry_run("/online_voice_agent")
        probe.confirm_dry_run("/object_track")
        probe.wait(
            lambda: probe.scans > 1 and probe.images > 1,
            30,
            "实际扫描或检测图像未到达",
        )
        if args.recall:
            recalled = probe.submit(
                "/online_agent/text", "我之前告诉你的验收代号是什么？只聊天。"
            )
            assert "蓝鹭" in recalled["reply"], recalled
            probe.submit("/online_agent/clear_memory", "clear", [])
            cleared = probe.submit(
                "/online_agent/text", "我之前告诉你的验收代号是什么？只聊天。"
            )
            assert "蓝鹭" not in cleared["reply"], cleared
        elif args.recording_only:
            # 录音动作验收先建立真实扫描前提，不预置识别文本。
            probe.submit(
                "/online_agent/text",
                "请开启激光融合，只调用 enable_lidar。",
                ["enable_lidar"],
            )
            before = probe.scans
            probe.wait(
                lambda: probe.scans >= before + 2, 5, "融合后扫描未到达"
            )
            recording = probe.submit("/online_agent/wav", args.wav)
            assert recording["transcript"], recording
            assert any(
                action["name"]
                in ("start_following", "start_tracking", "enable_tracking")
                and action["status"] == "real_success"
                for action in recording["actions"]
            ), recording
            probe.submit(
                "/online_agent/text",
                "请停止跟随，只调用 stop_following。",
                ["stop_following"],
            )
        else:
            # 2. 在线模型选择感知动作；观察扫描后才请求 Follow。
            probe.submit(
                "/online_agent/text",
                "请恢复相机采集，只调用 start_receiving_image。",
                ["start_receiving_image"],
            )
            probe.submit(
                "/online_agent/text",
                "请开启激光融合，只调用 enable_lidar。",
                ["enable_lidar"],
            )
            before = probe.scans
            probe.wait(
                lambda: probe.scans >= before + 2, 5, "融合后扫描未到达"
            )
            mixed = probe.submit(
                "/online_agent/text",
                "请严格依次调用 volume_set(35)、start_following、"
                "head_nod、head_nod、volume_status、stop_following。",
                [
                    "volume_set",
                    "start_following",
                    "head_nod",
                    "head_nod",
                    "volume_status",
                    "stop_following",
                ],
            )
            assert mixed["actions"][4]["data"]["level"] == 35
            probe.submit(
                "/online_agent/text",
                "请暂停相机采集，只调用 stop_camera_collection。",
                ["stop_camera_collection"],
            )
            probe.submit(
                "/online_agent/text",
                "请恢复相机采集，只调用 start_receiving_image。",
                ["start_receiving_image"],
            )
            # 3. 原录音经真实 ASR，不预置或猜测其文本。
            recording = probe.submit("/online_agent/wav", args.wav)
            assert recording["transcript"], recording
            probe.submit(
                "/online_agent/text",
                "我的验收代号是蓝鹭，请记住。只聊天，不执行动作。",
                [],
            )
            probe.submit(
                "/online_agent/text", "我的验收代号是什么？只聊天。", []
            )
        assert probe.count_publishers("/cmd_vel") == 0
        assert probe.count_publishers("/tracking/cmd_vel_safe") == 0
        passed = True
    finally:
        evidence = {
            "passed": passed,
            "phase": (
                "recall"
                if args.recall
                else "recording"
                if args.recording_only
                else "integration"
            ),
            "scan_messages": probe.scans,
            "detection_images": probe.images,
            "motion_messages": len(probe.motion),
            "results": probe.results,
        }
        directory = Path(args.evidence_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (evidence["phase"] + ".json")).write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        probe.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
