"""通过真实 ROS 传输与固定服务事件验证交互结果，不替代在线验收。"""

import asyncio
import threading
import time

import pytest
from test_online_interaction import FixedProvider, await_reconciliation

rclpy = pytest.importorskip("rclpy")
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.task import Future  # noqa: E402
from std_msgs.msg import Bool  # noqa: E402
from std_srvs.srv import SetBool  # noqa: E402

from robot_agent.actions.capabilities import (  # noqa: E402
    create_default_actions,
)
from robot_agent.actions.perception import (  # noqa: E402
    PerceptionActions,
    perception_actions,
)
from robot_agent.conversation.agent import Agent  # noqa: E402
from robot_agent.ros.perception import RosPerception  # noqa: E402
from robot_agent.ros.voice_node import RosExecutor  # noqa: E402


@pytest.fixture
def ros_devices():
    """隔离域内建立真实 ROS 服务端，设备响应内容由测试场景指定。"""
    rclpy.init()
    device = Node("object_track")
    device.declare_parameter("dry_run", True)
    agent_node = Node("perception_test_agent")
    events = []
    scenario = {
        "success": True,
        "message": "confirmed",
        "delay": 0.0,
        "delay_kind": "fusion",
    }

    def camera(message):
        """记录外部收到的采集请求。"""
        events.append(("camera", message.data))

    def follow(request, response):
        """固定 Follow 回执代表设备确认或拒绝。"""
        events.append(("follow", request.data))
        if scenario["delay_kind"] == "follow":
            time.sleep(scenario["delay"])
        response.success = scenario["success"]
        response.message = scenario["message"]
        return response

    def fusion(request, response):
        """模拟迟到融合回执，实际通过 ROS service 返回。"""
        events.append(("fusion", request.data))
        if scenario["delay_kind"] == "fusion":
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


async def run_with_receipts(interface, operation):
    """无论场景是否失败，都在所属事件循环关闭原 ROS 回执桥接。"""
    try:
        await operation
    finally:
        await interface.aclose(time.monotonic() + 1)


def make_agent(interface, functions):
    """通过现有注册表构造真实 ROS 感知交互 Interface。"""
    registry = create_default_actions().registry
    registry.register_many(
        perception_actions(PerceptionActions(interface, action_timeout=0.1))
    )
    return Agent(FixedProvider(functions), registry, action_timeout=0.1)


def test_ros_confirmations_without_agent_mode_gate(ros_devices):
    """Agent直接使用设备回执，不再读取或校验设备模式参数。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        device, interface, events, scenario = ros_devices
        agent = make_agent(
            interface,
            [
                {"name": "start_following", "arguments": {}},
                {"name": "disable_lidar", "arguments": {}},
            ],
        )
        result = await agent.submit("跟随后关闭融合")
        assert result.status == "completed", result
        assert ("fusion", True) in events and ("follow", True) in events
        device.set_parameters([Parameter("dry_run", value=False)])
        events.clear()
        result = await make_agent(
            interface,
            [
                {"name": "enable_lidar", "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ],
        ).submit("开启")
        assert result.status == "completed"
        assert result.actions[0].status == "real_success"
        assert ("fusion", True) in events

    asyncio.run(run_with_receipts(ros_devices[1], scenario()))


def test_ros_rejection_and_late_receipt(ros_devices):
    """真实传输下拒绝不跟随，超时不重发也不补执行。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        device, interface, events, scenario = ros_devices
        scenario.update(success=False, message="invalid camera <- laser TF")
        result = await make_agent(
            interface,
            [
                {"name": "start_following", "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ],
        ).submit("跟随")
        assert [a.status for a in result.actions] == [
            "failed",
            "not_executed",
        ]
        assert "invalid camera <- laser TF" in result.reply
        assert not any(kind == "follow" for kind, _ in events)
        events.clear()
        scenario.update(success=True, delay=0.25)
        agent = make_agent(
            interface,
            [
                {"name": "start_following", "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ],
        )
        result = await agent.submit("跟随")
        assert result.actions[0].status == "unknown"
        reconciled = await await_reconciliation(
            agent,
            result.turn_id,
            lambda reply: reply.actions[0].status == "failed",
        )
        assert reconciled.actions[1].status == "not_executed"
        assert "已确认融合" in reconciled.actions[0].detail
        assert events.count(("fusion", True)) == 1
        assert not any(kind == "follow" for kind, _ in events)

    asyncio.run(run_with_receipts(ros_devices[1], scenario()))


@pytest.mark.parametrize("success", [True, False])
def test_simple_late_receipt_keeps_loop_live_and_original_request(
    ros_devices, success
):
    """等待不阻塞应用，超时后核对原回执且旧快照保持未知。"""

    async def run():
        """在同一应用循环提交、核对并关闭。"""
        _, interface, events, device_response = ros_devices
        device_response.update(delay=0.3, success=success)
        agent = make_agent(
            interface,
            [
                {"name": "enable_lidar", "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ],
        )
        ticks = []

        async def heartbeat():
            """原生 ROS 等待期间继续处理应用工作。"""
            for _ in range(30):
                ticks.append(1)
                await asyncio.sleep(0.01)

        ticker = asyncio.create_task(heartbeat())
        try:
            original = await agent.submit("开启融合再点头")
            assert [a.status for a in original.actions] == [
                "unknown",
                "not_executed",
            ]
            assert len(ticks) >= 5
            assert (await agent.reconcile("other-turn")).status == "rejected"
            await asyncio.sleep(0.3)
            assert (await agent.submit("不要重发")).status == "busy"
            result = await await_reconciliation(
                agent,
                original.turn_id,
                lambda reply: reply.actions[0].status
                == ("real_success" if success else "failed"),
            )
            assert result.actions[1].status == "not_executed"
            assert original.actions[0].status == "unknown"
            assert events.count(("fusion", True)) == 1
        finally:
            await ticker
            await agent.aclose()

    asyncio.run(run())


def test_close_retains_executor_receipts_until_original_action_settles(
    ros_devices,
):
    """关闭在同一预算内等待原回执并保存事实，不能先停 executor。"""

    async def run():
        """应用与 ROS 桥接按顺序完成收尾。"""
        _, interface, events, response = ros_devices
        response.update(delay=0.3)
        agent = make_agent(
            interface, [{"name": "enable_lidar", "arguments": {}}]
        )
        original = await agent.submit("开启融合")
        assert original.actions[0].status == "unknown"
        deadline = time.monotonic() + 1
        await agent.aclose(deadline)
        assert agent.last_result.actions[0].status == "real_success"
        assert original.actions[0].status == "unknown"
        await interface.aclose(deadline)
        assert events == [("fusion", True)]

    asyncio.run(run_with_receipts(ros_devices[1], run()))


@pytest.mark.parametrize("already_done", [False, True])
def test_bridge_waiter_cancellation_never_cancels_original_ros_future(
    already_done,
):
    """外部 Future 已完成或本地等待被取消，回执桥接均正确收尾。"""

    class Client:
        """受控 ROS SDK Seam，保留外部原 Future 供确认取消语义。"""

        srv_name = "/tracking/set_lidar_enabled"

        def __init__(self):
            """原请求仅有一个 Future，没有撤回协议。"""
            self.original = Future()
            self.requests = []

        def service_is_ready(self):
            """受控服务已发现。"""
            return True

        def call_async(self, request):
            """返回同一个外部原 Future，观察是否发生重发。"""
            self.requests.append(request.data)
            return self.original

    class ReceiptNode:
        """仅替换外部 ROS 创建操作，不替换动作或应用实现。"""

        def create_publisher(self, *args):
            """此场景不执行相机发布。"""
            return None

        def create_client(self, *args):
            """两种感知服务共用本场景的受控外部请求。"""
            return client

    async def run():
        """目的等待取消后仍接收原回执，关闭后不得调度已关闭循环。"""
        errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, context: errors.append(context)
        )
        response = SetBool.Response(success=True, message="late confirmed")
        interface = RosPerception(ReceiptNode())
        if already_done:
            client.original.set_result(response)
            result = await interface.set_enabled(
                "fusion", True, time.monotonic() + 1
            )
            assert result["status"] == "real_success"
        else:
            waiter = asyncio.create_task(
                interface.set_enabled("fusion", True, time.monotonic() + 1)
            )
            await asyncio.sleep(0)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert not client.original.cancelled()
            client.original.set_result(response)
        await interface.aclose(time.monotonic() + 1)
        assert client.requests == [True]
        assert not client.original.cancelled()
        assert errors == []

    client = Client()
    asyncio.run(run())


def test_executor_callback_error_reaches_application_owner():
    """executor 异常退出不能把应用留在永远等待回执的状态。"""

    async def run():
        """显式启动并观察外部 ROS 回调的编程错误。"""
        rclpy.init()
        node = Node("executor_failure_probe")

        def broken_callback():
            """设备侧回调的错误必须交给主事件循环。"""
            raise ValueError("fixture callback failed")

        node.create_timer(0.01, broken_callback)
        executor = RosExecutor(node)
        executor.start()
        try:
            with pytest.raises(ValueError, match="fixture callback failed"):
                await asyncio.wait_for(executor.wait(), 2)
            with pytest.raises(ValueError, match="fixture callback failed"):
                await executor.aclose(time.monotonic() + 1)
        finally:
            node.destroy_node()
            rclpy.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("action", ["stop_following", "stop_camera"])
def test_late_standby_receipt_does_not_submit_remaining_compound_steps(
    ros_devices,
    action,
):
    """迟到的 Follow standby 仅更新确认事实，不能补发融合或相机关闭。"""

    async def run():
        """回合期限贯穿整个复合动作。"""
        _, interface, events, response = ros_devices
        response.update(delay=0.3, delay_kind="follow")
        agent = make_agent(
            interface,
            [
                {"name": action, "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ],
        )
        try:
            original = await agent.submit("停止跟随")
            assert original.actions[0].status == "unknown"
            reconciled = await await_reconciliation(
                agent,
                original.turn_id,
                lambda reply: reply.actions[0].status == "failed",
            )
            assert "Follow 已确认待机" in reconciled.reply
            assert reconciled.actions[1].status == "not_executed"
            assert events == [("follow", False)]
            assert original.actions[0].status == "unknown"
        finally:
            deadline = time.monotonic() + 1
            await agent.aclose(deadline)
            await interface.aclose(deadline)

    asyncio.run(run())


def test_close_deadline_keeps_unknown_and_detaches_late_bridge(ros_devices):
    """预算耗尽只终止本地等待，迟到设备回执不会变成伪取消或成功。"""

    async def run():
        """循环关闭前断开回执交接，executor 此时仍正常运行。"""
        _, interface, events, response = ros_devices
        response.update(delay=0.3)
        agent = make_agent(
            interface, [{"name": "enable_lidar", "arguments": {}}]
        )
        original = await agent.submit("开启融合")
        deadline = time.monotonic() + 0.01
        await agent.aclose(deadline)
        await interface.aclose(deadline)
        assert agent.last_result.actions[0].status == "unknown"
        assert original.actions[0].status == "unknown"
        assert events == [("fusion", True)]

    asyncio.run(run())
    # 真实 ROS executor 在应用循环关闭后仍能接收这次原请求的迟到响应。
    time.sleep(0.35)


@pytest.mark.parametrize("action", ["start_following", "enable_lidar"])
def test_missing_ros_devices_reject_without_following_steps(action):
    """没有相机订阅端或融合服务时，原始动作失败且余项保持未执行。"""

    async def run():
        """不创建任何设备或硬件节点。"""
        rclpy.init()
        node = Node("missing_device_agent")
        interface = RosPerception(node)
        agent = make_agent(
            interface,
            [
                {"name": action, "arguments": {}},
                {"name": "head_nod", "arguments": {}},
            ],
        )
        try:
            result = await agent.submit("执行")
            assert [a.status for a in result.actions] == [
                "failed",
                "not_executed",
            ]
            assert "不可用" in result.reply
        finally:
            deadline = time.monotonic() + 1
            await agent.aclose(deadline)
            await interface.aclose(deadline)
            node.destroy_node()
            rclpy.shutdown()

    asyncio.run(run())
