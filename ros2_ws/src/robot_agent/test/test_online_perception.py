"""从交互输入验证感知动作、真实回执与后续动作停止。"""

import threading

import pytest
from test_online_interaction import FixedProvider, await_reconciliation

from robot_agent.online_actions import ActionRegistry
from robot_agent.online_interaction import OnlineInteraction
from robot_agent.online_perception import PerceptionActions, perception_actions


class PerceptionInterface:
    """固定设备事件替代 ROS 传输，保留成功与拒绝语义。"""

    def __init__(self):
        """记录外部动作及下一次回执。"""
        self.events = []
        self.failure = None

    def camera(self, enabled):
        """记录采集请求，不伪造相机确认。"""
        self.events.append(("camera", enabled))
        return {
            "status": "real_success",
            "detail": "采集请求已发布，设备状态未确认",
        }

    def set_enabled(self, kind, enabled, deadline):
        """返回明确的服务结果。"""
        self.events.append((kind, enabled))
        return self.failure or {"status": "real_success", "detail": "服务确认"}


def test_follow_fusion_and_toggle_through_interaction():
    """跟随前先确认融合，切换基于本入口的最后确认状态。"""
    interface = PerceptionInterface()
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    provider = FixedProvider(
        ["start_following", "following_status", "toggle_following"]
    )
    result = OnlineInteraction(provider, registry).submit(
        "启动跟随，查询，然后停止"
    )
    assert result["status"] == "completed"
    assert interface.events == [
        ("camera", True),
        ("fusion", True),
        ("follow", True),
        ("follow", False),
        ("fusion", False),
    ]
    assert "本入口最后确认" in result["reply"]
    interface.failure = {
        "status": "failed",
        "detail": "waiting for camera <- laser TF",
    }
    provider.functions = ["start_following", "head_nod"]
    interface.events.clear()
    result = OnlineInteraction(provider, registry).submit("启动然后点头")
    assert interface.events == [("camera", True), ("fusion", True)]
    assert [a["status"] for a in result["actions"]] == [
        "failed",
        "not_executed",
    ]
    assert "laser TF" in result["reply"]


def test_late_fusion_does_not_start_follow_or_retry():
    """融合回执迟到后只核对，不补发 Follow 或后续表情。"""
    release = threading.Event()

    class LateInterface(PerceptionInterface):
        """融合服务等待外部回执。"""

        def set_enabled(self, kind, enabled, deadline):
            """记录请求，并在融合阶段阻塞。"""
            if kind == "fusion":
                release.wait(2)
            return super().set_enabled(kind, enabled, deadline)

    interface = LateInterface()
    registry = ActionRegistry()
    registry.register_many(
        perception_actions(PerceptionActions(interface, action_timeout=1.0))
    )
    agent = OnlineInteraction(
        FixedProvider(["start_following", "head_nod"]),
        registry,
        action_timeout=0.02,
    )
    try:
        result = agent.submit("跟随然后点头")
        assert [a["status"] for a in result["actions"]] == [
            "unknown",
            "not_executed",
        ]
        assert agent.submit("再次跟随")["status"] == "busy"
        release.set()
        reconciled = await_reconciliation(
            agent,
            result["turn_id"],
            lambda reply: reply["actions"][0]["status"] == "failed",
        )
        assert interface.events == [("camera", True), ("fusion", True)]
        assert reconciled["actions"][1]["status"] == "not_executed"
    finally:
        release.set()


@pytest.mark.parametrize(
    "reason",
    [
        "服务不可用",
        "拒绝：waiting for camera <- laser TF",
        "拒绝：waiting for a recent LaserScan",
        "拒绝：waiting for synchronized inputs",
    ],
)
def test_device_rejection_is_in_reply_and_stops_actions(reason):
    """保留实际失败原因，不用模型承诺替代设备回执。"""
    interface = PerceptionInterface()
    interface.failure = {"status": "failed", "detail": reason}
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    result = OnlineInteraction(
        FixedProvider(["enable_lidar", "start_following"]), registry
    ).submit("开启融合并跟随")
    assert [a["status"] for a in result["actions"]] == [
        "failed",
        "not_executed",
    ]
    assert reason in result["reply"]
    assert interface.events == [("fusion", True)]


@pytest.mark.parametrize("action", ["start_following", "start_tracking"])
def test_follow_aliases_preserve_the_same_sequence(action):
    """所有启动别名复用同一依赖顺序。"""
    interface = PerceptionInterface()
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    result = OnlineInteraction(FixedProvider([action]), registry).submit(
        "启动"
    )
    assert result["status"] == "completed"
    assert interface.events == [
        ("camera", True),
        ("fusion", True),
        ("follow", True),
    ]


def test_camera_aliases_standby_and_unknown_status():
    """采集启停不等于预览状态；融合关闭确认会隐含待机。"""
    interface = PerceptionInterface()
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    provider = FixedProvider(
        [
            "start_receiving_image",
            "stop_camera_collection",
            "query_camera_status",
            "query_person_tracking_status",
            "enable_lidar",
            "disable_lidar",
            "following_status",
        ]
    )
    result = OnlineInteraction(provider, registry).submit("操作并查询")
    assert result["status"] == "completed"
    assert interface.events == [
        ("camera", True),
        ("follow", False),
        ("camera", False),
        ("fusion", True),
        ("fusion", False),
    ]
    assert "设备状态未确认" in result["reply"]
    assert "相机采集状态未知" in result["reply"]
    assert '"follow": false' in result["actions"][-1]["detail"]
    assert "不是实时状态" in result["reply"]


def test_unknown_toggle_and_invalid_parameters_send_nothing():
    """没有确认依据不猜测切换，错误参数仍整表零执行。"""
    interface = PerceptionInterface()
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    provider = FixedProvider(["toggle_following"])
    agent = OnlineInteraction(provider, registry)
    assert agent.submit("切换")["actions"][0]["status"] == "failed"
    provider.functions = ["enable_lidar", "start_following(True)"]
    assert agent.submit("启动")["status"] == "rejected"
    assert interface.events == []


def test_tracking_only_and_full_stop_preserve_source_semantics():
    """单独 tracking 不自动开启融合，完整停止才依次关闭两者。"""
    interface = PerceptionInterface()
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    result = OnlineInteraction(
        FixedProvider(
            ["enable_tracking", "disable_tracking", "stop_following"]
        ),
        registry,
    ).submit("单独切换然后完整停止")
    assert result["status"] == "completed"
    assert interface.events == [
        ("follow", True),
        ("follow", False),
        ("follow", False),
        ("fusion", False),
    ]


def test_partial_perception_facts_survive_later_failure():
    """后阶段失败仍回复已提交采集和已确认待机，避免隐去执行事实。"""
    interface = PerceptionInterface()
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    interface.failure = {"status": "failed", "detail": "fusion refused"}
    result = OnlineInteraction(
        FixedProvider(["start_following"]), registry
    ).submit("启动")
    assert "采集请求已发布" in result["reply"]
    assert "fusion refused" in result["reply"]

    class MissingCamera(PerceptionInterface):
        """Follow 可以停止，但相机采集端已不再可用。"""

        def camera(self, enabled):
            """无订阅端时返回提交失败。"""
            return {"status": "failed", "detail": "相机无订阅端"}

    registry = ActionRegistry()
    registry.register_many(
        perception_actions(PerceptionActions(MissingCamera()))
    )
    result = OnlineInteraction(
        FixedProvider(["stop_camera_collection"]), registry
    ).submit("暂停采集")
    assert "Follow 已确认待机" in result["reply"]
    assert "相机无订阅端" in result["reply"]


def test_simulation_and_perception_share_one_turn_after_main_merge():
    """主线模拟状态与感知回执可在同一回合按序组合，保留各自结果来源。"""
    interface = PerceptionInterface()
    registry = ActionRegistry()
    registry.register_many(perception_actions(PerceptionActions(interface)))
    provider = FixedProvider(
        [
            "volume_set(35)",
            "enable_lidar",
            "enable_tracking",
            "volume_status",
            "stop_following",
        ]
    )
    result = OnlineInteraction(provider, registry).submit(
        "设置音量并开启跟随，查询后停止"
    )
    assert result["status"] == "completed"
    assert [action["status"] for action in result["actions"]] == [
        "simulated_success",
        "real_success",
        "real_success",
        "simulated_success",
        "real_success",
    ]
    assert result["actions"][3]["data"]["level"] == 35
    assert interface.events == [
        ("fusion", True),
        ("follow", True),
        ("follow", False),
        ("fusion", False),
    ]
