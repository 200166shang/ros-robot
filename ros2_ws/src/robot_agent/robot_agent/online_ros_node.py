"""ROS 2 在线文本入口，仅负责配置、话题接入及生命周期。"""

import json
import threading
from pathlib import Path
from typing import List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .online_actions import ActionRegistry
from .online_interaction import OnlineInteraction
from .online_memory import ConversationMemory
from .online_perception import PerceptionActions, perception_actions
from .online_perception_ros import RosPerception
from .online_provider import DashScopeProvider
from .online_simulation import simulate_cue


class OnlineRosNode(Node):
    """独立文本验收入口；调用者按回执逐项提交，不参与麦克风运行。"""

    def __init__(self) -> None:
        """读取外部配置，接入单回合交互 Interface。"""
        super().__init__("online_agent", parameter_overrides=[])
        # 1. 读取外部参数，凭证由 provider 从环境取得。
        config_file = self.declare_parameter("config_file", "").value
        if not isinstance(config_file, str) or not config_file:
            raise ValueError("必须指定外部 config_file 路径")
        with open(config_file, encoding="utf-8") as source:
            config = json.load(source)

        # 2. 组装交互 Implementation 与边缘 Adapters。
        action_timeout = float(config.get("action_timeout", 5.0))
        registry = ActionRegistry()
        perception = PerceptionActions(RosPerception(self), action_timeout)
        registry.register_many(perception_actions(perception))
        self._agent = OnlineInteraction(
            DashScopeProvider(config),
            registry,
            provider_timeout=float(config.get("provider_timeout", 60.0)),
            action_timeout=action_timeout,
            memory=ConversationMemory(
                Path(
                    config.get(
                        "memory_file",
                        "~/.local/state/ros-robot/conversation-summary.json",
                    )
                ),
                recent_turns=config.get("memory_recent_turns", 6),
                summary_trigger=config.get("memory_summary_trigger", 6),
            ),
        )
        # 3. 接入文本和结果话题，由交互模块管理回合执行。
        self._publisher = self.create_publisher(
            String, "/online_agent/result", 10
        )
        self._worker: Optional[threading.Thread] = None
        self._accepting = True
        self.create_subscription(
            String, "/online_agent/text", self._on_text, 10
        )
        self.create_subscription(
            String, "/online_agent/reconcile", self._on_reconcile, 10
        )
        self.create_subscription(
            String, "/online_agent/clear_memory", self._on_clear_memory, 10
        )
        cue = simulate_cue("startup")
        self.get_logger().info(cue["detail"])
        self.get_logger().info("Online text test ready")

    def _on_text(self, message: String) -> None:
        """后台处理独立验收回合；调用者收到回执后再提交下一项。"""
        if not self._accepting:
            return
        self._worker = threading.Thread(
            target=self._handle, args=(message.data,), daemon=True
        )
        self._worker.start()

    def _on_clear_memory(self, message: String) -> None:
        """只接受明确 clear 指令，发布清空两种记忆的结果。"""
        if self._accepting and message.data == "clear":
            self._publish(self._agent.clear_memory())

    def _on_reconcile(self, message: String) -> None:
        """按原 turn_id 核对迟到回执；非阻塞查询，不重发设备动作。"""
        if self._accepting:
            self._publish(self._agent.reconcile(message.data))

    def _handle(self, text: str) -> None:
        """把交互回执原样发布，并以回合标识记录脱敏日志。"""
        result = self._agent.submit(text)
        if self._accepting:
            self._publish(result)

    def _publish(self, result: dict) -> None:
        """发布结构化回复和动作结果，不记录凭证与 provider 内部异常。"""
        if not self._accepting:
            return
        if result["status"] == "failed":
            cue = simulate_cue("error")
            self.get_logger().info(cue["detail"])
        message = String()
        message.data = json.dumps(result, ensure_ascii=False)
        self._publisher.publish(message)
        self.get_logger().info(
            f"turn={result['turn_id']} status={result['status']}"
        )

    def stop(self) -> None:
        """停止接入与发布，避免退出时线程访问已销毁节点。"""
        self._accepting = False
        if self._worker is not None:
            self._worker.join()


def main(args: Optional[List[str]] = None) -> None:
    """初始化 ROS，退出时先停止交互接入再释放节点。"""
    # 1. 初始化 ROS 并建立薄入口，进入话题事件循环。
    rclpy.init(args=args)
    node = None
    try:
        node = OnlineRosNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 2. 先禁止后台发布，再销毁节点与 ROS 上下文。
        if node is not None:
            node.stop()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
