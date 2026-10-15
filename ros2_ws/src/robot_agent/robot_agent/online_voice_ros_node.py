"""ROS 2正常在线入口：唯一麦克风逐轮交互及退出生命周期。"""

import json
import threading
from typing import Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .online_actions import ActionRegistry
from .online_perception import PerceptionActions, perception_actions
from .online_perception_ros import RosPerception
from .online_runtime import DEFAULT_ACTION_TIMEOUT, load_config
from .online_simulation import simulate_cue
from .online_voice import OnlineVoice
from .online_voice_runtime import capture_turn, create_voice


def create_ros_voice(node: Node, config: Dict) -> OnlineVoice:
    """组装同一语音Implementation与ROS感知Adapter，供运行和独立验收。"""
    actions = ActionRegistry()
    perception = PerceptionActions(
        RosPerception(node),
        float(config.get("action_timeout", DEFAULT_ACTION_TIMEOUT)),
    )
    actions.register_many(perception_actions(perception))
    return create_voice(config, actions=actions)


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
        self._config = config
        self._voice = create_ros_voice(self, config)
        self._stop = threading.Event()
        self._publisher = self.create_publisher(
            String, "/online_agent/result", 10
        )
        self._microphone = threading.Thread(
            target=self._microphone_loop, name="online-microphone"
        )
        # 2. 正常入口只有麦克风；文本和WAV由独立验收进程提交。
        self.get_logger().info(simulate_cue("startup")["detail"])
        self.get_logger().info("Online voice ready; microphone input")
        self._microphone.start()

    def _microphone_loop(self) -> None:
        """上一轮识别、动作、合成/播放结束后才开始下一轮录音。"""
        while not self._stop.is_set():
            self.get_logger().info("开始麦克风录音")
            result = capture_turn(self._voice, self._config)
            if self._stop.is_set():
                return
            if result["status"] == "failed":
                self.get_logger().info(simulate_cue("error")["detail"])
            message = String()
            message.data = json.dumps(result, ensure_ascii=False)
            self._publisher.publish(message)
            self._stop.wait(0.2)

    def stop(self) -> None:
        """关闭语音连接并取消录制/播放，回收业务线程后才销毁节点。"""
        self._stop.set()
        self._voice.close()
        self._microphone.join()


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
        if node is not None:
            node.stop()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
