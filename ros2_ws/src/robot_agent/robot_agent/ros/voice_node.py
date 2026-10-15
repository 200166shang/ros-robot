"""ROS 2正常在线入口：唯一麦克风逐轮交互及退出生命周期。"""

import asyncio
import json
import signal
import threading
import time
from typing import Dict, List, Optional

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.perception import (
    PerceptionActions,
    perception_actions,
)
from robot_agent.actions.simulation import simulate_cue
from robot_agent.application import AgentApplication
from robot_agent.results import VoiceRecord, result_to_json
from robot_agent.ros.perception import RosPerception
from robot_agent.runtime import (
    DEFAULT_ACTION_TIMEOUT,
    build_application,
    load_config,
)


def create_ros_application(
    node: Node,
    config: Dict,
    *,
    input_mode: str = "recording",
    perception: Optional[RosPerception] = None,
) -> AgentApplication:
    """组装同一语音Implementation与ROS感知Adapter，供运行和独立验收。"""
    capabilities = create_default_actions()
    actions = capabilities.registry
    perception_capability = PerceptionActions(
        RosPerception(node) if perception is None else perception,
        float(config.get("action_timeout", DEFAULT_ACTION_TIMEOUT)),
    )
    actions.register_many(perception_actions(perception_capability))
    return build_application(
        config, capabilities=capabilities, input_mode=input_mode
    )


class OnlineVoiceRosNode(Node):
    """薄 ROS 接线；唯一应用由主事件循环明确运行和关闭。"""

    def __init__(self) -> None:
        """读取配置并接线；不启动麦克风、业务线程或事件循环。"""
        super().__init__("online_voice_agent")
        filename = self.declare_parameter("config_file", "").value
        if not isinstance(filename, str) or not filename:
            raise ValueError("必须指定外部 config_file 路径")
        self._config = load_config(filename)
        self._perception = RosPerception(self)
        self._voice: Optional[AgentApplication] = None
        self._publisher = self.create_publisher(
            String, "/online_agent/result", 10
        )

    async def run(self) -> None:
        """主循环只运行统一应用，不持有另一份回合或会话状态。"""
        self._voice = create_ros_application(
            self,
            self._config,
            input_mode="microphone",
            perception=self._perception,
        )
        self.get_logger().info(simulate_cue("startup")["detail"])
        self.get_logger().info("Online voice starting; continuous ASR input")
        await self._voice.run(self._publish)

    def _publish(self, result: VoiceRecord) -> None:
        """只发布执行事实；输入重连耗尽明确报告，不重复提交模型。"""
        if result.status == "failed":
            self.get_logger().info(simulate_cue("error")["detail"])
        message = String()
        message.data = json.dumps(result_to_json(result), ensure_ascii=False)
        self._publisher.publish(message)

    async def aclose(self, deadline: float) -> None:
        """应用收尾期间持续接收回执，最后才断开本地 ROS 桥接。"""
        try:
            if self._voice is not None:
                await self._voice.aclose(deadline)
        finally:
            await self._perception.aclose(deadline)


class RosExecutor:
    """显式拥有唯一 ROS executor 线程，并把线程异常交回应用循环。"""

    def __init__(self, *nodes: Node) -> None:
        """只组装 executor；start 才启动接收线程。"""
        self._executor = SingleThreadedExecutor()
        for node in nodes:
            self._executor.add_node(node)
        self._thread: Optional[threading.Thread] = None
        self._stopped: Optional[asyncio.Future] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._handoff = threading.Lock()

    def start(self) -> None:
        """在应用循环中建立线程到循环的完成通知。"""
        loop = asyncio.get_running_loop()
        self._loop = loop
        stopped = loop.create_future()
        self._stopped = stopped

        def spin():
            """线程只处理 ROS 回调，任何异常都由拥有者观察。"""
            error = None
            try:
                self._executor.spin()
            except BaseException as caught:
                error = caught
            with self._handoff:
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(stopped.set_result, error)

        self._thread = threading.Thread(
            target=spin, name="online-ros-executor", daemon=True
        )
        self._thread.start()

    async def wait(self) -> None:
        """executor 意外退出会立即结束上层等待，不隐藏回调错误。"""
        assert self._stopped is not None, "ROS executor 尚未启动"
        error = await asyncio.shield(self._stopped)
        if error is not None:
            raise error

    async def aclose(self, deadline: float) -> None:
        """停止接收并在剩余预算内回收线程，不阻塞应用循环。"""
        self._executor.shutdown(timeout_sec=0)
        if self._thread is None:
            return
        try:
            while self._thread.is_alive():
                if time.monotonic() >= deadline:
                    raise asyncio.TimeoutError(
                        "ROS executor 线程未在期限内退出"
                    )
                await asyncio.sleep(0.01)
            self._thread.join(0)
            # Foxy 在未完成回调时首次 shutdown 可能只设置退出标志。
            self._executor.shutdown(timeout_sec=0)
            await self.wait()
        finally:
            with self._handoff:
                self._loop = None


async def _run(args: Optional[List[str]]) -> None:
    """主事件循环拥有 ROS、应用、信号与明确的关闭顺序。"""
    rclpy.init(args=args)
    node = None
    executor = None
    tasks = []
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    handlers = {
        signum: signal.getsignal(signum)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        # Foxy 没有 signal_handler_options；由主循环接管退出信号。
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        node = OnlineVoiceRosNode()
        executor = RosExecutor(node)
        executor.start()
        tasks = [
            asyncio.create_task(node.run()),
            asyncio.create_task(executor.wait()),
            asyncio.create_task(stop.wait()),
        ]
        done, _ = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            task.result()
    finally:
        deadline = time.monotonic() + 5.0
        try:
            if node is not None:
                await node.aclose(deadline)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            try:
                if executor is not None:
                    await executor.aclose(deadline)
            finally:
                if node is not None:
                    node.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()
                for signum, handler in handlers.items():
                    loop.remove_signal_handler(signum)
                    signal.signal(signum, handler)


def main(args: Optional[List[str]] = None) -> None:
    """正常入口只启动麦克风；应用运行在 asyncio 主循环。"""
    asyncio.run(_run(args))
