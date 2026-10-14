"""ROS 2 语音接入：配置、话题、可选麦克风与退出生命周期。"""

import json
import threading
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .online_actions import ActionRegistry
from .online_interaction import make_result
from .online_perception import PerceptionActions, perception_actions
from .online_perception_ros import RosPerception
from .online_simulation import simulate_cue
from .online_voice_runtime import capture_turn, create_voice


class OnlineVoiceRosNode(Node):
    """薄 ROS 入口；采集、在线流程和会话规则均由交互模块组织。"""

    def __init__(self) -> None:
        """校验外部配置，组装语音 Interface 并注册接入话题。"""
        super().__init__("online_voice_agent")
        # 1. 入口保持 dry-run，配置和音频存储位置均来自外部文件。
        if self.declare_parameter("dry_run", True).value is not True:
            raise ValueError("在线语音入口要求 dry_run=true")
        filename = self.declare_parameter("config_file", "").value
        if not isinstance(filename, str) or not filename:
            raise ValueError("必须指定外部 config_file 路径")
        self._config = json.loads(
            Path(filename).expanduser().read_text(encoding="utf-8")
        )
        actions = ActionRegistry()
        perception = PerceptionActions(
            RosPerception(self), float(self._config.get("action_timeout", 5))
        )
        actions.register_many(perception_actions(perception))
        self._voice = create_voice(self._config, actions=actions)
        self._stop = threading.Event()
        self._processing = threading.Lock()
        self._publish_lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._microphone: Optional[threading.Thread] = None

        # 2. 三类输入共用同一回合；录音/文本直接输入，识别事件需要唤醒。
        self._publisher = self.create_publisher(
            String, "/online_agent/result", 10
        )
        self.create_subscription(String, "/online_agent/wav", self._on_wav, 10)
        self.create_subscription(
            String, "/online_agent/text", self._on_text, 10
        )
        self.create_subscription(
            String, "/online_agent/transcript", self._on_transcript, 10
        )
        self.create_subscription(
            String, "/online_agent/tts_enable", self._on_tts_enable, 10
        )
        self.create_subscription(
            String, "/online_agent/reconcile", self._on_reconcile, 10
        )
        self.create_subscription(
            String, "/online_agent/clear_memory", self._on_clear_memory, 10
        )
        self.create_timer(1.0, self._voice.tick)
        if self._config.get("microphone_enabled", False):
            self._microphone = threading.Thread(
                target=self._microphone_loop, name="online-microphone"
            )
            self._microphone.start()
        self.get_logger().info(simulate_cue("startup")["detail"])
        self.get_logger().info("Online voice ready; dry_run=true")

    def _on_wav(self, message: String) -> None:
        """非阻塞接纳录音路径，使用既有 capture Interface。"""
        self._start(
            lambda: capture_turn(self._voice, self._config, message.data)
        )

    def _on_text(self, message: String) -> None:
        """文本保持既有直接回合语义，额外合成可试听回复。"""
        self._start(
            lambda: self._voice.submit_transcript(message.data, direct=True)
        )

    def _on_transcript(self, message: String) -> None:
        """最终识别事件应用唤醒和连续会话规则。"""
        self._start(lambda: self._voice.submit_transcript(message.data))

    def _on_reconcile(self, message: String) -> None:
        """复用原回合标识核对迟到动作，绝不补执行后续动作。"""
        self._start(lambda: self._voice.reconcile(message.data))

    def _on_clear_memory(self, message: String) -> None:
        """复用主线记忆清空契约，回合忙碌时不重置上下文。"""
        if message.data == "clear":
            self._start(self._voice.clear_memory)

    def _on_tts_enable(self, message: String) -> None:
        """用显式 enable 命令恢复文本降级后的在线合成。"""
        if message.data == "enable":
            try:
                self._voice.enable_tts()
            except RuntimeError:
                self.get_logger().info("TTS reset deferred: turn busy")

    def _start(self, operation: Callable[[], Dict]) -> None:
        """后台运行单回合；捕获外部录音失败，忙时立即返回。"""
        if self._stop.is_set():
            return
        if not self._processing.acquire(blocking=False):
            self._publish(
                make_result(uuid.uuid4().hex, "busy", "正在处理上一回合。")
            )
            return
        self._worker = threading.Thread(
            target=self._handle, args=(operation,), name="online-voice-turn"
        )
        self._worker.start()

    def _handle(self, operation: Callable[[], Dict]) -> None:
        """发布已关联回执；外部文件/设备失败不遗留接入忙碌状态。"""
        try:
            result = operation()
        finally:
            self._processing.release()
        self._publish(result)

    def _microphone_loop(self) -> None:
        """可选半双工采集；每轮完成回复后才录制下一轮。"""
        while not self._stop.is_set():
            if self._processing.acquire(blocking=False):
                self._handle(lambda: capture_turn(self._voice, self._config))
            self._stop.wait(0.2)

    def _publish(self, result: Dict) -> None:
        """只发布脱敏回执，退出时不再访问 ROS publisher。"""
        with self._publish_lock:
            if self._stop.is_set():
                return
            if result["status"] == "failed":
                self.get_logger().info(simulate_cue("error")["detail"])
            message = String()
            message.data = json.dumps(result, ensure_ascii=False)
            self._publisher.publish(message)

    def stop(self) -> None:
        """先关闭在线连接，再等待有限录音/模型调用释放资源。"""
        with self._publish_lock:
            self._stop.set()
        self._voice.close()
        timeout = (
            float(self._config.get("provider_timeout", 60))
            + float(self._config.get("record_seconds", 8))
            + 20
        )
        for worker in (self._microphone, self._worker):
            if worker is not None:
                worker.join(timeout=timeout)


def main(args: Optional[List[str]] = None) -> None:
    """进入 ROS 生命周期，正常退出按连接、线程、节点顺序释放。"""
    # 1. 配置后由 ROS 驱动输入和静音定时器。
    rclpy.init(args=args)
    node = None
    try:
        node = OnlineVoiceRosNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # 2. 禁止发布并释放外部资源，最后销毁 ROS 上下文。
        if node is not None:
            node.stop()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
