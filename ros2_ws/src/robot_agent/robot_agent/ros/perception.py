"""ROS 感知 Adapter：相机请求话题及带设备确认的感知服务。"""

import asyncio
import threading
import time
from typing import Dict

from rclpy.node import Node
from std_msgs.msg import Bool
from std_srvs.srv import SetBool


class RosPerception:
    """专用 executor 接收回执，应用事件循环独占异步等待与状态。"""

    def __init__(self, node: Node) -> None:
        """沿用固定 tracker 名称和话题，不创建第二进程管理器。"""
        self._pending = {}
        self._handoff = threading.Lock()
        self._closed = False
        self._camera = node.create_publisher(Bool, "/enable_camera", 10)
        self._clients = {
            "follow": node.create_client(SetBool, "/tracking/set_enabled"),
            "fusion": node.create_client(
                SetBool, "/tracking/set_lidar_enabled"
            ),
        }

    def camera(self, enabled: bool) -> Dict:
        """没有采集端订阅时拒绝；发布完成不确认设备状态。"""
        if self._camera.get_subscription_count() == 0:
            return {
                "status": "failed",
                "detail": "相机采集控制不可用：/enable_camera 没有订阅端",
            }
        message = Bool()
        message.data = enabled
        self._camera.publish(message)
        return {
            "status": "real_success",
            "detail": "相机采集请求已发布："
            + str(enabled)
            + "；无设备确认，不代表图像预览、检测或硬件开关状态",
        }

    async def _call(self, client, request):
        """强持有原 ROS Future；取消本地等待不会撤回设备调用。"""
        loop = asyncio.get_running_loop()
        destination = loop.create_future()

        def observe(future):
            """即使本地等待被取消，也领取迟到传输异常。"""
            if not future.cancelled():
                future.exception()

        destination.add_done_callback(observe)
        original = client.call_async(request)
        self._pending[original] = destination

        def deliver():
            """只有应用循环可完成目的 Future，退出后不再写入。"""
            target = self._pending.pop(original, None)
            if target is None or target.done():
                return
            error = original.exception()
            if error is not None:
                target.set_exception(error)
            else:
                target.set_result(original.result())

        def receive(_future):
            """executor 回调只交接，不修改应用状态或阻塞线程。"""
            with self._handoff:
                if not self._closed:
                    loop.call_soon_threadsafe(deliver)

        original.add_done_callback(receive)
        return await asyncio.shield(destination)

    async def aclose(self, deadline: float) -> None:
        """收尾期间保留回执；期限后仅断开本地桥接，不撤回 ROS 调用。"""
        if self._pending:
            await asyncio.wait(
                set(self._pending.values()),
                timeout=max(0, deadline - time.monotonic()),
            )
        with self._handoff:
            self._closed = True
        for destination in self._pending.values():
            destination.cancel()
        self._pending.clear()

    async def set_enabled(
        self, kind: str, enabled: bool, deadline: float
    ) -> Dict:
        """直接调用设备Interface；仅最终服务回执可报告确认。"""
        if self._closed:
            raise RuntimeError("ROS 回执桥接已经关闭")
        client = self._clients[kind]
        if not client.service_is_ready():
            return {
                "status": "failed",
                "detail": client.srv_name + " 服务不可用",
            }

        # 设备服务负责TF、同步数据和近期扫描前提，入口不重复读取模式。
        if time.monotonic() >= deadline:
            return {
                "status": "failed",
                "detail": "动作期限已过，未提交行为请求，不补执行",
            }
        request = SetBool.Request()
        request.data = enabled
        response = await self._call(client, request)
        if response is None:
            return {
                "status": "unknown",
                "detail": "服务未返回回执，执行结果未确认",
            }
        return {
            "status": "real_success" if response.success else "failed",
            "detail": response.message,
        }
