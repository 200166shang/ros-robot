"""从文本交互 Interface 验证在线回合行为。"""

import json

from robot_agent.online_actions import ActionRegistry
from robot_agent.online_interaction import OnlineInteraction


class FixedProvider:
    """替代外部模型，提供固定的完整输出或流式片段。"""

    def __init__(self, functions=(), response="你好"):
        """保存本轮模型输出。"""
        self.functions = functions
        self.response = response

    def complete(self, text, timeout):
        """返回旧在线契约的 JSON。"""
        return json.dumps({"function": list(self.functions), "response": self.response})


def test_chat_and_repeated_actions_across_turns():
    """普通聊天及跨回合重复动作均经公共入口得到可信结果。"""
    provider = FixedProvider()
    agent = OnlineInteraction(provider, ActionRegistry())
    assert agent.submit("你好")["reply"] == "你好"
    provider.functions = ["head_nod", "head_smile", "head_nod"]
    first = agent.submit("点头微笑点头")
    second = agent.submit("再做一次")
    assert [a["name"] for a in first["actions"]] == ["head_nod", "head_smile", "head_nod"]
    assert [a["status"] for a in second["actions"]] == ["simulated_success"] * 3
    assert first["turn_id"] != second["turn_id"]
    assert "模拟" in first["reply"]


def test_invalid_list_executes_nothing():
    """后项无效时首项也不能执行。"""
    events = []

    def execute():
        """代表外部设备记录实际发出的调用。"""
        events.append("sent")
        return {"status": "real_success"}

    registry = ActionRegistry()
    registry.register("device", execute)
    for invalid in ("unknown", "head_nod(1)", "head_nod(x=1)", "head_nod(__import__('os'))"):
        agent = OnlineInteraction(FixedProvider(["device", invalid]), registry)
        assert agent.submit("执行")["status"] == "rejected"
    assert events == []


def test_failure_stops_and_reports_remaining():
    """失败回执保留前项成功与后项未执行。"""
    registry = ActionRegistry()

    def fail():
        """返回外部设备的失败回执。"""
        return {"status": "failed"}

    registry.register("failure", fail)
    agent = OnlineInteraction(
        FixedProvider(["head_nod", "failure", "head_smile"], "已经全成功"), registry
    )
    result = agent.submit("执行")
    assert [a["status"] for a in result["actions"]] == [
        "simulated_success",
        "failed",
        "not_executed",
    ]
    assert "已经全成功" not in result["reply"]


def test_stream_fragments_execute_list_once():
    """增量片段组装完毕后列表只执行一次，兼容本地契约。"""

    class StreamProvider:
        """代表增量在线模型输出。"""

        def complete(self, text, timeout):
            """按字符提供 JSON 片段。"""
            return iter('{"fc":["head_nod","head_nod"],"res":"已完成"}')

    result = OnlineInteraction(StreamProvider(), ActionRegistry()).submit("执行")
    assert len(result["actions"]) == 2
    assert result["status"] == "completed"


def test_action_timeout_is_unknown_and_busy_until_return():
    """在途超时保持未知且阻止新回合，不重试动作。"""
    import threading

    released = threading.Event()
    sent = threading.Event()

    def slow():
        """模拟已发出且尚未确认的外部调用。"""
        sent.set()
        released.wait(2)
        return {"status": "real_success"}

    registry = ActionRegistry()
    registry.register("slow", slow)
    agent = OnlineInteraction(FixedProvider(["slow", "head_nod"]), registry, action_timeout=0.02)
    try:
        result = agent.submit("执行")
        assert sent.is_set()
        assert [a["status"] for a in result["actions"]] == ["unknown", "not_executed"]
        assert agent.submit("再次执行")["status"] == "busy"
    finally:
        released.set()


def test_provider_timeout_and_busy_rejection():
    """模型超时不执行动作，处理中的第二回合立即拒绝。"""
    import threading

    entered = threading.Event()
    released = threading.Event()

    class SlowProvider:
        """代表阻塞的模型连接。"""

        def complete(self, text, timeout):
            """等待外部响应释放。"""
            entered.set()
            released.wait(2)
            return '{"function":["head_nod"],"response":"好了"}'

    agent = OnlineInteraction(SlowProvider(), ActionRegistry(), provider_timeout=0.1)
    results = []
    worker = threading.Thread(target=lambda: results.append(agent.submit("你好")))
    worker.start()
    try:
        assert entered.wait(1)
        assert agent.submit("第二轮")["status"] == "busy"
        worker.join(1)
        assert results[0]["actions"] == []
        assert results[0]["status"] == "failed"
    finally:
        released.set()
        worker.join(1)


def test_exception_and_invalid_receipt_cannot_be_success():
    """执行异常或非法回执不记作成功。"""
    registry = ActionRegistry()

    def error():
        """模拟外部调用异常。"""
        raise RuntimeError("internal secret")

    registry.register("error", error)
    result = OnlineInteraction(FixedProvider(["error", "head_nod"]), registry).submit("执行")
    assert result["actions"][0]["status"] == "unknown"
    assert "internal secret" not in str(result)


def test_parameter_validation_precedes_all_execution():
    """设备参数校验失败整表拒绝；有效字面量参数保持原序。"""
    events = []

    def position(pitch=0):
        """记录设备 Adapter 的公开输入并返回确认。"""
        events.append(pitch)
        return {"status": "real_success", "detail": "已确认"}

    def validate(pitch=0):
        """拒绝超出源头部角度范围的参数。"""
        if type(pitch) not in (int, float) or not 65 <= pitch <= 120:
            raise ValueError("pitch 越界")

    registry = ActionRegistry()
    registry.register("head_position", position, validate)
    provider = FixedProvider(["head_position(70)", "head_position(pitch=200)"])
    agent = OnlineInteraction(provider, registry)
    assert agent.submit("执行")["status"] == "rejected"
    assert events == []
    provider.functions = ["head_position(70)", "head_position(pitch=80)"]
    result = agent.submit("执行")
    assert events == [70, 80]
    assert [a["parameters"] for a in result["actions"]] == [{"pitch": 70}, {"pitch": 80}]
    assert [a["status"] for a in result["actions"]] == ["real_success", "real_success"]


def test_duplicate_json_and_unconfirmed_receipt_rejected():
    """歧义 JSON 整表拒绝，无效设备回执报告未知。"""

    class DuplicateProvider:
        """提供有歧义的外部输出。"""

        def complete(self, text, timeout):
            """返回重复字段。"""
            return '{"function":[],"function":["head_nod"],"response":"好了"}'

    assert (
        OnlineInteraction(DuplicateProvider(), ActionRegistry()).submit("执行")["status"]
        == "rejected"
    )
    registry = ActionRegistry()

    def invalid():
        """模拟不符合设备回执契约的响应。"""
        return "设备调用失败"

    registry.register("invalid", invalid)
    result = OnlineInteraction(FixedProvider(["invalid", "head_nod"]), registry).submit("执行")
    assert [a["status"] for a in result["actions"]] == ["unknown", "not_executed"]


def test_call_syntax_defaults_and_literal_arguments_remain_compatible():
    """文本入口仍接受裸函数、空调用、位置/关键字参数与默认值。"""
    registry = ActionRegistry()

    def display(message="默认", options=None):
        """设备回执携带收到的业务参数，供交互结果观察。"""
        return {"status": "simulated_success", "detail": message}

    registry.register("display", display)
    provider = FixedProvider(
        [
            "head_nod()",
            "display",
            "display()",
            "display('你好', {'colors': ['red'], 'enabled': True})",
            "display(options=None, message='关键字')",
        ]
    )
    result = OnlineInteraction(provider, registry).submit("按顺序显示")
    assert result["status"] == "completed"
    assert [action["parameters"] for action in result["actions"]] == [
        {},
        {"message": "默认", "options": None},
        {"message": "默认", "options": None},
        {"message": "你好", "options": {"colors": ["red"], "enabled": True}},
        {"message": "关键字", "options": None},
    ]


def test_unsupported_call_forms_reject_the_whole_list():
    """展开参数、重复参数和属性调用均不能越过整表校验。"""
    registry = ActionRegistry()
    provider = FixedProvider()
    agent = OnlineInteraction(provider, registry)
    for source in (
        "head_nod(*[])",
        "head_nod(**{})",
        "head_nod(x=1, x=2)",
        "device.head_nod()",
        "head_nod(1+2)",
    ):
        provider.functions = ["head_smile", source]
        result = agent.submit("执行")
        assert result["status"] == "rejected"
        assert result["actions"] == []


def test_late_action_requires_explicit_reconciliation():
    """动作线程结束后仍保持忙，只有核对迟到回执才恢复。"""
    import threading
    import time

    release = threading.Event()
    returned = threading.Event()

    def slow():
        """代表不可取消的设备调用。"""
        release.wait(2)
        returned.set()
        return {"status": "real_success", "detail": "设备确认完成"}

    registry = ActionRegistry()
    registry.register("slow", slow)
    provider = FixedProvider(["head_nod", "slow", "head_smile"])
    agent = OnlineInteraction(provider, registry, action_timeout=0.02)
    try:
        result = agent.submit("执行")
        release.set()
        assert returned.wait(1)
        assert agent.submit("下一轮")["status"] == "busy"
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            reconciled = agent.reconcile(result["turn_id"])
            if reconciled["actions"][1]["status"] == "real_success":
                break
            time.sleep(0.005)
        assert [a["status"] for a in reconciled["actions"]] == [
            "simulated_success",
            "real_success",
            "not_executed",
        ]
        provider.functions = []
        assert agent.submit("你好")["status"] == "completed"
        assert result["actions"][1]["status"] == "unknown"
    finally:
        release.set()


def test_reporting_failure_preserves_completed_action(monkeypatch):
    """回复格式异常不能把已执行动作报告为模型失败或未发出。"""
    import robot_agent.online_interaction as interaction

    def broken_reply(actions):
        """在输出边界注入格式化异常。"""
        raise ValueError("private error")

    monkeypatch.setattr(interaction, "confirmed_action_reply", broken_reply)
    result = OnlineInteraction(FixedProvider(["head_nod"]), ActionRegistry()).submit("执行")
    assert result["status"] == "failed"
    assert result["actions"][0]["status"] == "simulated_success"
    assert "未发出动作" not in result["reply"]
    assert "模型不可用" not in result["reply"]
    assert "private error" not in str(result)


def test_uncertain_late_receipt_does_not_restore_service():
    """迟到的未知或异常回执不能恢复接入，核对不重试动作。"""
    import threading
    import time

    for raises in (False, True):
        release = threading.Event()
        calls = []

        def slow():
            """模拟设备完成 I/O 后仍不能确认最终状态。"""
            calls.append("sent")
            release.wait(2)
            if raises:
                raise RuntimeError("private failure")
            return {"status": "unknown", "detail": "设备无法确认"}

        registry = ActionRegistry()
        registry.register("slow", slow)
        agent = OnlineInteraction(
            FixedProvider(["slow", "head_nod"]), registry, action_timeout=0.02
        )
        try:
            result = agent.submit("执行")
            assert agent.reconcile("wrong-id")["status"] == "rejected"
            release.set()
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                reconciled = agent.reconcile(result["turn_id"])
                if "最终状态仍未知" in reconciled["reply"]:
                    break
                time.sleep(0.005)
            assert "最终状态仍未知" in reconciled["reply"]
            assert [a["status"] for a in reconciled["actions"]] == ["unknown", "not_executed"]
            assert agent.submit("下一轮")["status"] == "busy"
            assert calls == ["sent"]
        finally:
            release.set()


def test_late_failure_reconciles_without_executing_remaining_actions():
    """设备明确失败也能解除不确定状态，后续动作不补执行。"""
    import threading
    import time

    release = threading.Event()

    def slow_failure():
        """提供迟到的明确失败回执。"""
        release.wait(2)
        return {"status": "failed", "detail": "设备确认失败"}

    registry = ActionRegistry()
    registry.register("slow_failure", slow_failure)
    provider = FixedProvider(["slow_failure", "head_nod"])
    agent = OnlineInteraction(provider, registry, action_timeout=0.02)
    try:
        result = agent.submit("执行")
        release.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            reconciled = agent.reconcile(result["turn_id"])
            if reconciled["actions"][0]["status"] == "failed":
                break
            time.sleep(0.005)
        assert [a["status"] for a in reconciled["actions"]] == ["failed", "not_executed"]
        provider.functions = []
        assert agent.submit("聊天")["status"] == "completed"
    finally:
        release.set()


def test_validation_exception_reports_its_stage_and_executes_nothing():
    """设备校验器异常属于校验阶段，不误报模型不可用。"""
    calls = []

    def execute():
        """记录设备调用以证明校验阶段没有提交动作。"""
        calls.append("sent")
        return {"status": "real_success"}

    def validate():
        """模拟参数校验依赖故障。"""
        raise RuntimeError("private validation failure")

    registry = ActionRegistry()
    registry.register("device", execute, validate)
    result = OnlineInteraction(FixedProvider(["head_nod", "device"]), registry).submit("执行")
    assert result["status"] == "failed"
    assert result["actions"] == []
    assert "校验异常" in result["reply"]
    assert calls == []
