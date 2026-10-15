"""通过 Agent 和应用入口验证执行事实的不可变快照。"""

import asyncio
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Dict, List

import pytest
from test_online_interaction import FixedProvider
from test_online_voice import FixedSpeech, FixedTTS

from robot_agent.actions.contracts import ActionInput
from robot_agent.actions.registry import ActionRegistry
from robot_agent.application import AgentApplication
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.memory import ConversationMemory
from robot_agent.results import result_to_json


class DeviceInput(ActionInput):
    """设备自定义嵌套参数。"""

    options: Dict[str, List[str]]


def test_agent_returns_named_nested_snapshot():
    """参数和回执脱离设备可变对象，调用者不能改写既有事实。"""
    data = {"positions": [{"x": 3}], "labels": ["ready"]}

    def device(options):
        """设备可以修改本地参数，但报告必须保留原请求。"""
        options["colors"].append("blue")
        return {"status": "real_success", "data": data}

    registry = ActionRegistry()
    registry.register("device", device, inputs=DeviceInput)
    agent = Agent(
        FixedProvider(
            [{"name": "device", "arguments": {"options": {"colors": ["red"]}}}]
        ),
        registry,
    )
    result = asyncio.run(agent.submit("执行"))
    assert result.status == "completed"
    assert result.actions[0].parameters["options"]["colors"] == ("red",)
    data["positions"][0]["x"] = 99
    data["labels"].append("changed")
    assert result.actions[0].data["positions"][0]["x"] == 3
    assert result.actions[0].data["labels"] == ("ready",)
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"
    with pytest.raises(TypeError):
        result.actions[0].data["positions"][0]["x"] = 5


def test_voice_failures_keep_execution_and_flat_json(tmp_path, monkeypatch):
    """输出与保存失败分别报告，保留成功动作和未执行余项。"""

    class SummaryFailure(FixedProvider):
        """正常请求可用，外部摘要模型报告连接故障。"""

        def complete(self, text, timeout, *, tools=None):
            """摘要失败不能改写此前的动作事实。"""
            if "【摘要任务】" in text:
                raise OSError("summary unavailable")
            return super().complete(text, timeout, tools=tools)

    registry = ActionRegistry()
    registry.register("confirmed", lambda: {"status": "real_success"})
    registry.register(
        "failure", lambda: {"status": "failed", "detail": "refused"}
    )
    agent = Agent(
        SummaryFailure(
            [
                {"name": "confirmed", "arguments": {}},
                {"name": "failure", "arguments": {}},
                {"name": "confirmed", "arguments": {}},
            ]
        ),
        registry,
        memory=ConversationMemory(tmp_path / "memory", 1, 1),
    )
    tts = FixedTTS()
    tts.failures = 1
    app = AgentApplication(
        agent, FixedSpeech(), tts, tmp_path, lambda: False, tts_attempts=1
    )
    original = Path.replace

    def failed_save(path, destination):
        """在磁盘出口模拟原子提交失败。"""
        raise OSError("disk offline")

    monkeypatch.setattr(Path, "replace", failed_save)
    record = asyncio.run(app.submit_transcript("原识别文本", direct=True))
    assert record.turn.status == "failed"
    assert [action.status for action in record.turn.actions] == [
        "real_success",
        "failed",
        "not_executed",
    ]
    assert record.turn.memory_warnings == ("summary_failed",)
    assert record.tts_status == "failed"
    assert record.record_status == "failed"
    payload = result_to_json(record)
    assert payload == {
        "turn_id": record.turn_id,
        "status": "failed",
        "reply": (
            "confirmed：真实接口确认成功；failure：失败，refused；"
            "confirmed：未执行。"
        ),
        "actions": [
            {
                "name": "confirmed",
                "parameters": {},
                "status": "real_success",
                "detail": "",
            },
            {
                "name": "failure",
                "parameters": {},
                "status": "failed",
                "detail": "refused",
            },
            {"name": "confirmed", "parameters": {}, "status": "not_executed"},
        ],
        "memory_warnings": ["summary_failed"],
        "transcript": "原识别文本",
        "session_state": "standby",
        "tts_status": "failed",
        "record_status": "failed",
    }
    assert json.loads(json.dumps(payload)) == payload
    monkeypatch.setattr(Path, "replace", original)
    asyncio.run(app.aclose())
