"""ROS 感知 Adapter：只复用相机话题、确认服务与只读安全参数。"""

import threading
import time
from typing import Dict

from rcl_interfaces.msg import ParameterType
from rcl_interfaces.srv import GetParameters
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
        self._parameters = node.create_client(
            GetParameters, "/object_track/get_parameters"
        )

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
        """启用前验证实际 dry-run；仅最终服务回执可报告确认。"""
        client = self._clients[kind]
        if not client.service_is_ready():
            return {
                "status": "failed",
                "detail": client.srv_name + " 服务不可用",
            }

        # 1. 启用行为前读取设备安全参数，不能仅相信入口的 dry_run。
        if enabled:
            if not self._parameters.service_is_ready():
                return {
                    "status": "failed",
                    "detail": "无法确认 dry_run=true，未提交启用请求",
                }
            request = GetParameters.Request()
            request.names = ["dry_run"]
            response = self._call(self._parameters, request)
            if response is None or len(response.values) != 1:
                return {
                    "status": "failed",
                    "detail": "设备未返回 dry_run 参数，未提交启用请求",
                }
            parameter = response.values[0]
            if (
                parameter.type != ParameterType.PARAMETER_BOOL
                or not parameter.bool_value
            ):
                return {
                    "status": "failed",
                    "detail": "ObjectTrack dry_run 不是 true，未提交启用请求",
                }

        # 2. 服务端保留 TF、近期扫描、同步数据检查，不重试或降级。
        if time.monotonic() >= deadline:
            return {
                "status": "failed",
                "detail": "安全参数回执迟到，未提交行为请求，不补执行",
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
