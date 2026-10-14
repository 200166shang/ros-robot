"""通过真实 ROS 传输与固定服务事件验证交互结果，不替代在线验收。"""

import threading
import time

import pytest
from test_online_interaction import FixedProvider, await_reconciliation

rclpy = pytest.importorskip("rclpy")
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402
from std_srvs.srv import SetBool  # noqa: E402

from robot_agent.online_actions import ActionRegistry  # noqa: E402
from robot_agent.online_interaction import OnlineInteraction  # noqa: E402
from robot_agent.online_perception import (  # noqa: E402
    PerceptionActions,
    perception_actions,
)
from robot_agent.online_perception_ros import RosPerception  # noqa: E402


@pytest.fixture
def ros_devices():
    """隔离域内建立真实 ROS 服务端，设备响应内容由测试场景指定。"""
    rclpy.init()
    device = Node("object_track")
    device.declare_parameter("dry_run", True)
    agent_node = Node("perception_test_agent")
    events = []
    scenario = {"success": True, "message": "confirmed", "delay": 0.0}

    def camera(message):
        """记录外部收到的采集请求。"""
        events.append(("camera", message.data))

    def follow(request, response):
        """固定 Follow 回执代表设备确认或拒绝。"""
        events.append(("follow", request.data))
        response.success = scenario["success"]
        response.message = scenario["message"]
        return response

    def fusion(request, response):
        """模拟迟到融合回执，实际通过 ROS service 返回。"""
        events.append(("fusion", request.data))
        time.sleep(scenario["delay"])
        response.success = scenario["success"]
        response.message = scenario["message"]
        return response

    device.create_subscription(Bool, "/enable_camera", camera, 10)
    device.create_service(SetBool, "/tracking/set_enabled", follow)
    device.create_service(SetBool, "/tracking/set_lidar_enabled", fusion)
    interface = RosPerception(agent_node)
    executor = SingleThreadedExecutor()
    executor.add_node(device)
    executor.add_node(agent_node)
    worker = threading.Thread(target=executor.spin)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (
                agent_node.count_subscribers("/enable_camera")
                and "/tracking/set_enabled"
                in dict(agent_node.get_service_names_and_types())
                and "/object_track/get_parameters"
                in dict(agent_node.get_service_names_and_types())
            ):
                break
            time.sleep(0.02)
        yield device, interface, events, scenario
    finally:
        executor.shutdown()
        worker.join(2)
        agent_node.destroy_node()
        device.destroy_node()
        rclpy.shutdown()


def make_agent(interface, functions):
    """通过现有注册表构造真实 ROS 感知交互 Interface。"""
    registry = ActionRegistry()
    registry.register_many(
        perception_actions(PerceptionActions(interface, action_timeout=0.1))
    )
    return OnlineInteraction(
        FixedProvider(functions), registry, action_timeout=0.1
    )


def test_ros_confirmations_without_agent_mode_gate(ros_devices):
    """Agent直接使用设备回执，不再读取或校验设备模式参数。"""
    device, interface, events, scenario = ros_devices
    agent = make_agent(interface, ["start_following", "disable_lidar"])
    result = agent.submit("跟随后关闭融合")
    assert result["status"] == "completed", result
    assert ("fusion", True) in events and ("follow", True) in events
    device.set_parameters([Parameter("dry_run", value=False)])
    events.clear()
    result = make_agent(interface, ["enable_lidar", "head_nod"]).submit("开启")
    assert result["status"] == "completed"
    assert result["actions"][0]["status"] == "real_success"
    assert ("fusion", True) in events


def test_ros_rejection_and_late_receipt(ros_devices):
    """真实传输下拒绝不跟随，超时不重发也不补执行。"""
    device, interface, events, scenario = ros_devices
    scenario.update(success=False, message="invalid camera <- laser TF")
    result = make_agent(interface, ["start_following", "head_nod"]).submit(
        "跟随"
    )
    assert [a["status"] for a in result["actions"]] == [
        "failed",
        "not_executed",
    ]
    assert "invalid camera <- laser TF" in result["reply"]
    assert not any(kind == "follow" for kind, _ in events)
    events.clear()
    scenario.update(success=True, delay=0.25)
    agent = make_agent(interface, ["start_following", "head_nod"])
    result = agent.submit("跟随")
    assert result["actions"][0]["status"] == "unknown"
    reconciled = await_reconciliation(
        agent,
        result["turn_id"],
        lambda reply: reply["actions"][0]["status"] == "failed",
    )
    assert reconciled["actions"][1]["status"] == "not_executed"
    assert events.count(("fusion", True)) == 1
    assert not any(kind == "follow" for kind, _ in events)
