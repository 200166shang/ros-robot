"""ROS 2正常在线入口：唯一麦克风逐轮交互及退出生命周期。"""

import asyncio
import json
import threading
from typing import Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.perception import (
    PerceptionActions,
    perception_actions,
)
from robot_agent.actions.simulation import simulate_cue
from robot_agent.application import AgentApplication
from robot_agent.ros.perception import RosPerception
from robot_agent.runtime import (
    DEFAULT_ACTION_TIMEOUT,
    build_application,
    load_config,
)


def create_ros_application(
    node: Node, config: Dict, *, input_mode: str = "recording"
) -> AgentApplication:
    """组装同一语音Implementation与ROS感知Adapter，供运行和独立验收。"""
    capabilities = create_default_actions()
    actions = capabilities.registry
    perception = PerceptionActions(
        RosPerception(node),
        float(config.get("action_timeout", DEFAULT_ACTION_TIMEOUT)),
    )
    actions.register_many(perception_actions(perception))
    return build_application(
        config, capabilities=capabilities, input_mode=input_mode
    )


class OnlineVoiceRosNode(Node):
    """唯一业务线程录音、交互和回复；ROS executor只处理设备回执。"""

    def __init__(self) -> None:
        """读取外部配置，组装感知和语音，启动唯一麦克风循环。"""
        super().__init__("online_voice_agent")
        # 1. 外部配置和音频存储位置由部署者提供。
        filename = self.declare_parameter("config_file", "").value
        if not isinstance(filename, str) or not filename:
            raise ValueError("必须指定外部 config_file 路径")
        config = load_config(filename)
        self._voice = create_ros_application(
            self, config, input_mode="microphone"
        )
        self._loop = asyncio.new_event_loop()
        self._publisher = self.create_publisher(
            String, "/online_agent/result", 10
        )
        self._microphone = threading.Thread(
            target=self._microphone_loop, name="online-microphone"
        )
        # 2. 正常入口只有麦克风；文本和WAV由独立验收进程提交。
        self.get_logger().info(simulate_cue("startup")["detail"])
        self.get_logger().info("Online voice starting; continuous ASR input")
        self._microphone.start()

    def _microphone_loop(self) -> None:
        """持续ASR交付完整句，业务顺序处理；传输线程保活并丢弃暂停音频。"""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._voice.run(self._publish))

    def _publish(self, result: Dict) -> None:
        """只发布执行事实；输入重连耗尽明确报告，不重复提交模型。"""
        if result["status"] == "failed":
            self.get_logger().info(simulate_cue("error")["detail"])
        message = String()
        message.data = json.dumps(result, ensure_ascii=False)
        self._publisher.publish(message)

    def stop(self) -> None:
        """关闭语音连接并取消录制/播放，回收业务线程后才销毁节点。"""

        def close_application() -> None:
            """在业务所属事件循环发起关闭。"""
            self._loop.create_task(self._voice.aclose())

        self._loop.call_soon_threadsafe(close_application)
        self._microphone.join()
        self._loop.close()


def main(args: Optional[List[str]] = None) -> None:
    """主executor处理ROS回执，退出先结束麦克风线程再释放节点。"""
    # 1. 固定麦克风业务线程与ROS executor分别承担顺序交互和回执。
    rclpy.init(args=args)
    node = None
    try:
        node = OnlineVoiceRosNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 2. 录音/播放取消及业务线程回收完成后再销毁publisher。
        try:
            if node is not None:
                try:
                    node.stop()
                finally:
                    node.destroy_node()
        finally:
            if rclpy.ok():
                rclpy.shutdown()
