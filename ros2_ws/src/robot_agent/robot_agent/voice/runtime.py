"""在线语音组装与独立录音验收入口，所有运行产物保存在源码外。"""

import argparse
import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from typing import Dict

from robot_agent.application import AgentApplication
from robot_agent.results import make_result
from robot_agent.runtime import build_application, load_config
from robot_audio.audio_sources import create_audio_source


async def capture_turn(voice: AgentApplication, wav_path: str) -> Dict:
    """独立WAV验收使用文件Adapter，不进入正常持续麦克风链路。"""
    source = create_audio_source("wav_file", input_wav_path=wav_path)
    # 临时目录属于外部运行数据，capture 和在线识别完成后立即删除副本。
    with tempfile.TemporaryDirectory(prefix="online-voice-") as directory:
        path = Path(directory) / "input.wav"
        try:
            source.capture(path)
        except (OSError, ValueError, RuntimeError):
            result = make_result(
                uuid.uuid4().hex, "failed", "录音输入不可用，本轮未发出动作。"
            )
            result["input_status"] = "failed"
            return result
        return await voice.submit_recording(path, direct=True)


def main() -> None:
    """执行一轮真实录音链路，输出结构化回执并关闭在线连接。"""
    parser = argparse.ArgumentParser(description="独立在线WAV验收")
    parser.add_argument("--config", required=True)
    parser.add_argument("--wav", required=True)
    args = parser.parse_args()
    asyncio.run(_run_recording(load_config(args.config), args.wav))


async def _run_recording(config: Dict, wav_path: str) -> None:
    """单个事件循环拥有文件识别、应用回合和退出。"""
    voice = build_application(config)
    try:
        result = await capture_turn(voice, wav_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if (
            result["status"] != "completed"
            or result.get("tts_status") != "completed"
        ):
            raise SystemExit(1)
    finally:
        await voice.aclose()


if __name__ == "__main__":
    main()
