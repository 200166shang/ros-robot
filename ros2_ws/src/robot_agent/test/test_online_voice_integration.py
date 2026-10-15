"""通过语音组装 Interface 验证合入主线的记忆与感知能力。"""

import asyncio
import json
import wave
from pathlib import Path

from async_speech_fixture import acknowledge, event, final, speech_server
from test_online_speech import fixture_wav

from robot_agent.actions.capabilities import create_default_actions
from robot_agent.actions.perception import (
    PerceptionActions,
    perception_actions,
)
from robot_agent.conversation.provider import DashScopeProvider
from robot_agent.results import ModelReply, ToolCall, result_to_json
from robot_agent.runtime import build_application
from robot_agent.voice.runtime import capture_turn
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

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fixed-test-key")
        inputs = []

        async def recognize(self, path, timeout):
            """以固定最终事件替换在线传输。"""
            return "我叫小明，请查询相机状态并点头"

        async def complete(self, text, deadline, *, tools=None):
            """从公开 provider Interface 观察上下文与摘要请求。"""
            inputs.append(text)
            if "【摘要任务】" in text:
                return ModelReply(
                    "用户叫小明",
                    None,
                )
            return ModelReply(
                "模型的提前承诺",
                ToolCall(
                    "fixture_call",
                    "execute_actions",
                    {
                        "actions": [
                            {"name": "query_camera_status", "arguments": {}},
                            {"name": "head_nod", "arguments": {}},
                        ]
                    },
                ),
            )

        async def synthesize(self, text, path, timeout):
            """仅保存行为测试音频替身。"""
            path.write_bytes(b"fixed speech")

        monkeypatch.setattr(DashScopeASR, "recognize", recognize)
        monkeypatch.setattr(DashScopeProvider, "complete", complete)
        monkeypatch.setattr(DashScopeTTS, "synthesize", synthesize)
        capabilities = create_default_actions()
        actions = capabilities.registry
        actions.register_many(
            perception_actions(PerceptionActions(FixedPerception()))
        )
        config = {
            "output_dir": str(tmp_path / "audio"),
            "memory_file": str(tmp_path / "memory.json"),
            "memory_recent_turns": 2,
            "memory_summary_trigger": 2,
        }
        voice = build_application(config, capabilities=capabilities)
        try:
            first = await voice.submit_recording(tmp_path / "input.wav")
            assert first.actions[0].status == "real_success"
            assert first.actions[1].status == "simulated_success"
            assert "模型的提前承诺" not in first.reply
            assert (
                await voice.submit_transcript("第二轮", direct=True)
            ).status == "completed"
            context = json.loads(inputs[1].split("\n", 1)[1])
            assert context["recent_exchanges"][0]["user"] == first.transcript
            assert context["recent_exchanges"][0]["assistant"] == first.reply
            assert (
                json.loads((tmp_path / "memory.json").read_text())["summary"]
                == "用户叫小明"
            )
        finally:
            (await voice.aclose())
        restarted = build_application(config, capabilities=capabilities)
        try:
            (await restarted.submit_transcript("重启后", direct=True))
            assert "用户叫小明" in inputs[-1]
            assert (await restarted.clear_memory()).status == "completed"
            (await restarted.submit_transcript("清空后", direct=True))
            assert inputs[-1] == "清空后"
        finally:
            (await restarted.aclose())

    asyncio.run(scenario())


def test_wav_runtime_preserves_actions_reply_audio_and_record(
    tmp_path, monkeypatch
):
    """独立 WAV 通过真实语音任务协议进入模型和动作主线并关联产物。"""

    async def scenario():
        """同一循环持有回合、连接与迟到回执。"""
        synthesized = []
        closed = []

        async def handler(socket):
            """真实本机协议确认整文件识别与流式TTS。"""
            command = await acknowledge(socket)
            if command["payload"]["task"] == "asr":
                async for message in socket:
                    if isinstance(message, str):
                        assert (
                            json.loads(message)["header"]["action"]
                            == "finish-task"
                        )
                        await final(socket, command, "真实句一。真实句二。")
                        await event(socket, command, "task-finished")
                        break
            else:
                synthesized.append(
                    json.loads(await socket.recv())["payload"]["input"]["text"]
                )
                await socket.recv()
                await socket.send(bytes(4800))
                await event(socket, command, "task-finished")
            await socket.wait_closed()
            closed.append(True)

        model_inputs = []

        async def complete(self, text, deadline, *, tools=None):
            """固定模型外部结果，保留动作解析、执行和确认回复主线。"""
            model_inputs.append(text)
            return ModelReply(
                "模型的提前承诺",
                ToolCall(
                    "fixture_call",
                    "execute_actions",
                    {"actions": [{"name": "head_nod", "arguments": {}}]},
                ),
            )

        monkeypatch.setattr(DashScopeProvider, "complete", complete)
        directory = tmp_path / "output"
        async with speech_server(monkeypatch, handler):
            voice = build_application({"output_dir": str(directory)})
            try:
                result = await capture_turn(voice, str(fixture_wav(tmp_path)))
            finally:
                await voice.aclose()

        assert model_inputs == ["真实句一。真实句二。"]
        assert result.transcript == model_inputs[0]
        assert result.actions[0].status == "simulated_success"
        assert "模型的提前承诺" not in result.reply
        assert result.tts_status == "completed"
        assert synthesized == [result.reply]
        audio_path = Path(result.audio_path)
        assert audio_path == directory / (result.turn_id + ".wav")
        with wave.open(str(audio_path)) as audio:
            assert audio.getnframes() == 2400
        record = json.loads(
            (directory / (result.turn_id + ".json")).read_text()
        )
        assert record["transcript"] == result.transcript
        assert record["reply"] == result.reply
        assert record["actions"] == result_to_json(result)["actions"]
        assert record["audio_path"] == result.audio_path
        assert closed == [True, True]

    asyncio.run(scenario())
