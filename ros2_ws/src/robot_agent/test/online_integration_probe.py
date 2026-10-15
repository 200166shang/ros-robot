"""独立文本/WAV验收：复用正常交互与真实ROS感知，不接入麦克风节点。"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from time import monotonic
from typing import Callable, Dict, List, Optional, Union

import rclpy
from geometry_msgs.msg import Twist
from rcl_interfaces.msg import ParameterType
from rcl_interfaces.srv import GetParameters
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image, LaserScan

from robot_agent.application import AgentApplication
from robot_agent.results import TurnResult, VoiceRecord, result_to_json
from robot_agent.ros.perception import RosPerception
from robot_agent.ros.voice_node import RosExecutor, create_ros_application
from robot_agent.runtime import load_config
from robot_agent.voice.runtime import capture_turn


class OnlineIntegrationProbe(Node):
    """独立验收进程；单一调用者逐项提交，ROS线程只接收设备回执。"""

    def __init__(self, config: Dict) -> None:
        """记录公开回执、真实传感器数据和两个运动出口。"""
        super().__init__("online_integration_probe")
        self._config = config
        self.results: List[Union[TurnResult, VoiceRecord]] = []
        self.motion: List[Twist] = []
        self.scans = 0
        self.images = 0
        for topic in ("/cmd_vel", "/tracking/cmd_vel_safe"):
            self.create_subscription(Twist, topic, self.motion.append, 10)
        self.create_subscription(
            LaserScan, "/scan", self._scan, qos_profile_sensor_data
        )
        self.create_subscription(
            Image, "/camera/image_det", self._image, qos_profile_sensor_data
        )

    def _scan(self, message: LaserScan) -> None:
        """累计真实雷达输入，不使用固定扫描替代。"""
        self.scans += 1

    def _image(self, message: Image) -> None:
        """累计实际检测标注图像，作为 Follow 输入前提证据。"""
        self.images += 1

    async def wait(
        self, predicate: Callable[[], bool], timeout: float, description: str
    ) -> None:
        """有界处理回调，验收条件未满足时直接失败。"""
        deadline = monotonic() + timeout
        while not predicate():
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AssertionError(description)
            await asyncio.sleep(min(remaining, 0.05))

    async def confirm_dry_run(self, name: str) -> None:
        """读取实际节点参数，不能用入口意图代替设备安全确认。"""
        client = self.create_client(GetParameters, name + "/get_parameters")
        await self.wait(client.service_is_ready, 15, "安全参数服务未发现")
        request = GetParameters.Request()
        request.names = ["dry_run"]
        future = client.call_async(request)
        await self.wait(future.done, 5, "安全参数未回复")
        response = future.result()
        assert response is not None, "安全参数未返回回执"
        values = response.values
        assert len(values) == 1
        assert values[0].type == ParameterType.PARAMETER_BOOL
        assert values[0].bool_value is True
        self.destroy_client(client)

    async def submit(
        self,
        voice: AgentApplication,
        kind: str,
        text: str,
        expected: Optional[List[str]] = None,
    ) -> Union[TurnResult, VoiceRecord]:
        """真实输入等待完整在线回复，失败不重试，不替换模型选择。"""
        operations = {
            "text": lambda: voice.submit_transcript(text, direct=True),
            "wav": lambda: capture_turn(voice, text),
            "clear_memory": voice.clear_memory,
        }
        result = await operations[kind]()
        self.results.append(result)
        print(
            json.dumps(result_to_json(result), ensure_ascii=False), flush=True
        )
        assert result.status == "completed", result
        if isinstance(result, VoiceRecord):
            assert result.tts_status == "completed", result
            assert result.record_status == "completed", result
            assert not result.turn.memory_warnings, result
        if expected is not None:
            assert [a.name for a in result.actions] == expected, result
            for action in result.actions:
                status = (
                    "simulated_success"
                    if action.name.startswith(("volume_", "head_"))
                    else "real_success"
                )
                assert action.status == status, result
        assert not self.motion, "dry-run 出现运动输出"
        return result


async def _run() -> None:
    """运行综合或重启阶段；原始回执和计数保存到源码外指定目录。"""
    parser = argparse.ArgumentParser(description="真实在线综合验收")
    parser.add_argument("--config", required=True)
    parser.add_argument("--wav", required=True)
    parser.add_argument("--evidence-dir", required=True)
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--recall", action="store_true")
    phase.add_argument("--recording-only", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    rclpy.init()
    probe = OnlineIntegrationProbe(config)
    executor = RosExecutor(probe)
    executor.start()
    perception = RosPerception(probe)
    voice = None
    passed = False
    try:
        # 1. 独立组装同一交互Implementation，确认实际tracker及数据。
        voice = create_ros_application(probe, config, perception=perception)
        await probe.confirm_dry_run("/object_track")
        await probe.wait(
            lambda: probe.scans > 1 and probe.images > 1,
            30,
            "实际扫描或检测图像未到达",
        )
        if args.recall:
            recalled = await probe.submit(
                voice, "text", "我之前告诉你的验收代号是什么？只聊天。"
            )
            assert "蓝鹭" in recalled.reply, recalled
            await probe.submit(voice, "clear_memory", "clear", [])
            cleared = await probe.submit(
                voice, "text", "我之前告诉你的验收代号是什么？只聊天。"
            )
            assert "蓝鹭" not in cleared.reply, cleared
        elif args.recording_only:
            # 录音动作验收先建立真实扫描前提，不预置识别文本。
            await probe.submit(
                voice,
                "text",
                "请开启激光融合，只调用 enable_lidar。",
                ["enable_lidar"],
            )
            before = probe.scans
            await probe.wait(
                lambda: probe.scans >= before + 2, 5, "融合后扫描未到达"
            )
            recording = await probe.submit(voice, "wav", args.wav)
            assert isinstance(recording, VoiceRecord)
            assert recording.transcript, recording
            assert any(
                action.name
                in ("start_following", "start_tracking", "enable_tracking")
                and action.status == "real_success"
                for action in recording.actions
            ), recording
            await probe.submit(
                voice,
                "text",
                "请停止跟随，只调用 stop_following。",
                ["stop_following"],
            )
        else:
            # 2. 在线模型选择感知动作；观察扫描后才请求 Follow。
            await probe.submit(
                voice,
                "text",
                "请恢复相机采集，只调用 start_receiving_image。",
                ["start_receiving_image"],
            )
            await probe.submit(
                voice,
                "text",
                "请开启激光融合，只调用 enable_lidar。",
                ["enable_lidar"],
            )
            before = probe.scans
            await probe.wait(
                lambda: probe.scans >= before + 2, 5, "融合后扫描未到达"
            )
            mixed = await probe.submit(
                voice,
                "text",
                "请一次提交原生 execute_actions 完整有序计划，音量设为35，"
                "启动跟随，连续两次点头，查询音量，停止跟随。",
                [
                    "volume_set",
                    "start_following",
                    "head_nod",
                    "head_nod",
                    "volume_status",
                    "stop_following",
                ],
            )
            assert mixed.actions[4].data is not None
            assert mixed.actions[4].data["level"] == 35
            await probe.submit(
                voice,
                "text",
                "请暂停相机采集，只调用 stop_camera_collection。",
                ["stop_camera_collection"],
            )
            await probe.submit(
                voice,
                "text",
                "请恢复相机采集，只调用 start_receiving_image。",
                ["start_receiving_image"],
            )
            # 3. 原录音经真实 ASR，不预置或猜测其文本。
            recording = await probe.submit(voice, "wav", args.wav)
            assert isinstance(recording, VoiceRecord)
            assert recording.transcript, recording
            await probe.submit(
                voice,
                "text",
                "我的验收代号是蓝鹭，请记住。只聊天，不执行动作。",
                [],
            )
            await probe.submit(
                voice, "text", "我的验收代号是什么？只聊天。", []
            )
        assert probe.count_publishers("/cmd_vel") == 0
        assert probe.count_publishers("/tracking/cmd_vel_safe") == 0
        passed = True
    finally:
        acceptance_error = sys.exc_info()[1]
        try:
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
                "results": [
                    result_to_json(result) for result in probe.results
                ],
            }
            directory = Path(args.evidence_dir).expanduser()
            # 保存失败仍输出完整执行事实；已有验收异常优先显露。
            try:
                directory.mkdir(parents=True, exist_ok=True)
                (directory / (evidence["phase"] + ".json")).write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                print(
                    json.dumps(
                        {"evidence_status": "failed", "evidence": evidence},
                        ensure_ascii=False,
                    ),
                    file=sys.stderr,
                )
                if acceptance_error is None:
                    raise
        finally:
            deadline = monotonic() + 5
            try:
                if voice is not None:
                    await voice.aclose(deadline)
            finally:
                try:
                    await perception.aclose(deadline)
                finally:
                    try:
                        await executor.aclose(deadline)
                    finally:
                        try:
                            probe.destroy_node()
                        finally:
                            rclpy.shutdown()


def main() -> None:
    """同一事件循环拥有整个验收生命周期，退出后不遗留请求。"""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
