"""感知动作流程：复用设备 Interface，不管理进程或输出运动命令。"""

import json
import time
from typing import Dict, Optional, Protocol

from robot_agent.actions.contracts import ActionHandler, action_deadline


class PerceptionInterface(Protocol):
    """相机发布与已确认的跟随服务，传输在边缘变化。"""

    def camera(self, enabled: bool) -> Dict:
        """提交采集请求；成功只代表发布完成。"""
        ...

    def set_enabled(self, kind: str, enabled: bool, deadline: float) -> Dict:
        """等待服务最终回执；在途超时由交互 Interface 管理。"""
        ...


class PerceptionActions:
    """集中组织相机、融合和 Follow，状态只记录本入口最后回执。"""

    def __init__(
        self, interface: PerceptionInterface, action_timeout: float = 5.0
    ) -> None:
        """启动时不猜测其他入口控制的状态。"""
        self._interface = interface
        self._action_timeout = action_timeout
        self._follow: Optional[bool] = None
        self._fusion: Optional[bool] = None

    def start_camera(self) -> Dict:
        """恢复采集，不把发布完成当作设备开启确认。"""
        return self._interface.camera(True)

    def stop_camera(self) -> Dict:
        """先确认 Follow standby，再暂停采集，失败则不继续。"""
        # 1. Follow 待机回执确认后，才提交无确认的相机开关。
        deadline = action_deadline(self._action_timeout)
        receipt = self.disable_tracking()
        if receipt["status"] != "real_success":
            return receipt
        # 2. 只报告采集请求提交，不能声称相机硬件已停机。
        if time.monotonic() >= deadline:
            return {
                "status": "failed",
                "detail": "Follow 已确认待机，但回执迟到；未提交相机暂停请求",
            }
        receipt = self._interface.camera(False)
        return {
            "status": receipt["status"],
            "detail": "Follow 已确认待机；" + receipt["detail"],
        }

    def camera_status(self) -> Dict:
        """相机开关话题没有状态查询服务，不从本地意图推断状态。"""
        return {
            "status": "real_success",
            "detail": "相机采集状态未知：/enable_camera 无状态回执",
        }

    def _set_state(
        self, kind: str, enabled: bool, deadline: Optional[float] = None
    ) -> Dict:
        """成功服务回执更新记录，失败不推断设备当前状态。"""
        if deadline is None:
            deadline = action_deadline(self._action_timeout)
        receipt = self._interface.set_enabled(kind, enabled, deadline)
        confirmed = enabled if receipt["status"] == "real_success" else None
        if kind == "follow":
            self._follow = confirmed
        else:
            self._fusion = confirmed
            if confirmed is False:
                self._follow = False
        return receipt

    def enable_lidar(self) -> Dict:
        """开启 tracker 扫描融合，保留服务端 TF/发布端检查。"""
        return self._set_state("fusion", True)

    def disable_lidar(self) -> Dict:
        """关闭融合，服务确认后记录其隐含的 Follow standby。"""
        return self._set_state("fusion", False)

    def start_following(self) -> Dict:
        """采集请求、融合确认、Follow 确认按序执行，不重试。"""
        # 1. 恢复相机采集，成功仅代表请求已发布。
        deadline = action_deadline(self._action_timeout)
        if time.monotonic() >= deadline:
            return {
                "status": "failed",
                "detail": "动作期限已过，未提交采集或跟随请求",
            }
        receipt = self.start_camera()
        if receipt["status"] != "real_success":
            return receipt
        # 2. 融合失败即停止，不越过 TF 和 LiDAR 前提。
        receipt = self._set_state("fusion", True, deadline)
        if receipt["status"] != "real_success":
            return {
                "status": receipt["status"],
                "detail": "采集请求已发布，无设备确认；融合："
                + receipt["detail"],
            }
        # 3. 服务端检查同步数据和近期扫描，不做相机跟随降级。
        if time.monotonic() >= deadline:
            return {
                "status": "failed",
                "detail": "融合回执迟到：已确认融合，未提交 Follow，不补执行",
            }
        fusion_detail = receipt["detail"]
        receipt = self._set_state("follow", True, deadline)
        return {
            "status": receipt["status"],
            "detail": "采集请求已发布，无设备确认；融合已确认："
            + fusion_detail
            + "；Follow："
            + receipt["detail"],
        }

    def enable_tracking(self) -> Dict:
        """仅启用 Follow，保留融合尚未开启时服务端拒绝的语义。"""
        return self._set_state("follow", True)

    def disable_tracking(self) -> Dict:
        """仅进入 Follow 待机，保持当前融合订阅。"""
        return self._set_state("follow", False)

    def stop_following(self) -> Dict:
        """按源动作先进入待机，再关闭融合；拒绝或超时不继续。"""
        # 1. 服务确认 Follow standby，不能把提交请求当作停止。
        deadline = action_deadline(self._action_timeout)
        receipt = self._set_state("follow", False, deadline)
        if receipt["status"] != "real_success":
            return receipt
        # 2. 同一截止时间内关闭融合，不重试或补执行。
        follow_detail = receipt["detail"]
        if time.monotonic() >= deadline:
            return {
                "status": "failed",
                "detail": "Follow 已确认待机，但回执迟到；未提交融合关闭请求",
            }
        receipt = self._set_state("fusion", False, deadline)
        return {
            "status": receipt["status"],
            "detail": "Follow 已确认待机："
            + follow_detail
            + "；融合："
            + receipt["detail"],
        }

    def toggle_following(self) -> Dict:
        """只切换本入口有确认依据的状态，未知时拒绝猜测。"""
        if self._follow is None:
            return {
                "status": "failed",
                "detail": "Follow 状态未知，请明确启动或停止；不自动猜测切换",
            }
        return (
            self.stop_following() if self._follow else self.start_following()
        )

    def following_status(self) -> Dict:
        """区分本入口最后确认与当前实时状态，外部控制可改变设备。"""
        detail = json.dumps(
            {"follow": self._follow, "fusion": self._fusion},
            ensure_ascii=False,
        )
        return {
            "status": "real_success",
            "detail": "本入口最后确认："
            + detail
            + "；不是实时状态，外部控制或节点重启可能改变状态",
        }


def perception_actions(
    perception: PerceptionActions,
) -> Dict[str, ActionHandler]:
    """声明感知动作及兼容名称，入口负责批量注册，流程不依赖注册表。"""
    return {
        "start_receiving_image": ActionHandler(perception.start_camera),
        "start_camera": ActionHandler(perception.start_camera),
        "stop_camera_collection": ActionHandler(perception.stop_camera),
        "stop_camera": ActionHandler(perception.stop_camera),
        "query_camera_status": ActionHandler(perception.camera_status),
        "start_following": ActionHandler(perception.start_following),
        "start_tracking": ActionHandler(perception.start_following),
        "enable_tracking": ActionHandler(perception.enable_tracking),
        "stop_following": ActionHandler(perception.stop_following),
        "disable_tracking": ActionHandler(perception.disable_tracking),
        "toggle_following": ActionHandler(perception.toggle_following),
        "following_status": ActionHandler(perception.following_status),
        "query_person_tracking_status": ActionHandler(
            perception.following_status
        ),
        "enable_lidar": ActionHandler(perception.enable_lidar),
        "disable_lidar": ActionHandler(perception.disable_lidar),
    }
