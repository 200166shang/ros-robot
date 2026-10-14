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
