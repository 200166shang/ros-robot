"""ROS 感知 Adapter：只复用相机话题、确认服务与只读安全参数。"""

import threading
import time
from typing import Dict

from rclpy.node import Node
from std_msgs.msg import Bool
from std_srvs.srv import SetBool


class RosPerception:
    """后台动作等待 ROS 回执，主 executor 持续处理响应，不二次 spin。"""

    def __init__(self, node: Node) -> None:
        """沿用固定 tracker 名称和话题，不创建第二进程管理器。"""
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

    def _call(self, client, request):
        """等待不可取消的已发出调用；交互超时不重发且保留迟到回执。"""
        future = client.call_async(request)
        ready = threading.Event()
        future.add_done_callback(lambda _future: ready.set())
        ready.wait()
        return future.result()

    def set_enabled(self, kind: str, enabled: bool, deadline: float) -> Dict:
        """直接调用设备Interface；仅最终服务回执可报告确认。"""
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
        response = self._call(client, request)
        if response is None:
            return {
                "status": "unknown",
                "detail": "服务未返回回执，执行结果未确认",
            }
        return {
            "status": "real_success" if response.success else "failed",
            "detail": response.message,
        }
