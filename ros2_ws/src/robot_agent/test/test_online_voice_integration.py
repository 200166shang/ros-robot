"""通过语音组装 Interface 验证合入主线的记忆与感知能力。"""

import json

from robot_agent.actions.perception import (
    PerceptionActions,
    perception_actions,
)
from robot_agent.actions.registry import ActionRegistry
from robot_agent.conversation.provider import DashScopeProvider
from robot_agent.voice.runtime import create_voice
from robot_agent.voice.speech import DashScopeASR, DashScopeTTS


class FixedPerception:
    """替换真实设备传输，保留主线感知动作流程。"""

    def camera(self, enabled):
        """按真实回执契约确认请求发布。"""
        return {"status": "real_success", "detail": "采集请求已发布"}

    def set_enabled(self, kind, enabled, deadline):
        """设备 Adapter 确认状态，测试不输出实际运动。"""
        return {"status": "real_success", "detail": "服务已确认"}


def test_voice_runtime_retains_perception_and_memory(tmp_path, monkeypatch):
    """录音回合包含感知回执，记忆跨回合/重启保持并能显式清空。"""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fixed-test-key")
    inputs = []

    def recognize(self, path, timeout):
        """以固定最终事件替换在线传输。"""
        return "我叫小明，请查询相机状态并点头"

    def complete(self, text, timeout):
        """从公开 provider Interface 观察上下文与摘要请求。"""
        inputs.append(text)
        if "【摘要任务】" in text:
            return json.dumps({"function": [], "response": "用户叫小明"})
        return json.dumps(
            {
                "function": ["query_camera_status", "head_nod"],
                "response": "模型的提前承诺",
            }
        )

    def synthesize(self, text, path, timeout):
        """仅保存行为测试音频替身。"""
        path.write_bytes(b"fixed speech")

    monkeypatch.setattr(DashScopeASR, "recognize", recognize)
    monkeypatch.setattr(DashScopeProvider, "complete", complete)
    monkeypatch.setattr(DashScopeTTS, "synthesize", synthesize)
    actions = ActionRegistry()
    actions.register_many(
        perception_actions(PerceptionActions(FixedPerception()))
    )
    config = {
        "output_dir": str(tmp_path / "audio"),
        "memory_file": str(tmp_path / "memory.json"),
        "memory_recent_turns": 2,
        "memory_summary_trigger": 2,
    }
    voice = create_voice(config, actions=actions)
    try:
        first = voice.submit_recording(tmp_path / "input.wav")
        assert first["actions"][0]["status"] == "real_success"
        assert first["actions"][1]["status"] == "simulated_success"
        assert "模型的提前承诺" not in first["reply"]
        assert (
            voice.submit_transcript("第二轮", direct=True)["status"]
            == "completed"
        )
        context = json.loads(inputs[1].split("\n", 1)[1])
        assert context["recent_exchanges"][0]["user"] == first["transcript"]
        assert context["recent_exchanges"][0]["assistant"] == first["reply"]
        assert (
            json.loads((tmp_path / "memory.json").read_text())["summary"]
            == "用户叫小明"
        )
    finally:
        voice.close()
    restarted = create_voice(config, actions=actions)
    try:
        restarted.submit_transcript("重启后", direct=True)
        assert "用户叫小明" in inputs[-1]
        assert restarted.clear_memory()["status"] == "completed"
        restarted.submit_transcript("清空后", direct=True)
        assert inputs[-1] == "清空后"
    finally:
        restarted.close()
