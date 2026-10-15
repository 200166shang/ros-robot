"""在线语音组装与独立录音验收入口，所有运行产物保存在源码外。"""

import argparse
import json
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

from robot_agent.actions.registry import ActionRegistry
from robot_agent.conversation.interaction import make_result
from robot_agent.runtime import create_interaction, load_config
from robot_agent.voice.session import OnlineVoice
from robot_agent.voice.speech import DashScopeASR, DashScopeTTS
from robot_audio.audio_io import play_wav
from robot_audio.audio_sources import create_audio_source


def create_voice(
    config: Dict, actions: Optional[ActionRegistry] = None
) -> OnlineVoice:
    """组装已有文本/动作和语音 Adapters；始终保持缺失设备模拟。"""
    directory = Path(config["output_dir"]).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[5]
    if directory == checkout or checkout in directory.parents:
        raise ValueError("output_dir 必须在源码目录外")
    if actions is None:
        actions = ActionRegistry()
    playback: Optional[Callable[[Path], None]] = None
    if config.get("playback_enabled", False):

        def play_reply(path: Path) -> None:
            """播放已保存的完整回复音频，设备异常不影响回合释放。"""
            play_wav(
                config.get("play_executable", "aplay"),
                config.get("play_device", "default"),
                path,
                cancelled=lambda: voice.state == "closed",
            )

        playback = play_reply

    voice = OnlineVoice(
        create_interaction(config, actions),
        DashScopeASR(config),
        DashScopeTTS(config),
        directory,
        music_playing=lambda: actions.music.is_playing,
        playback=playback,
        silence_timeout=float(config.get("silence_timeout", 120)),
        speech_timeout=float(config.get("speech_timeout", 60)),
        tts_attempts=int(config.get("tts_attempts", 3)),
        failure_threshold=int(config.get("tts_failure_threshold", 5)),
        retry_delay=float(config.get("tts_retry_delay", 1)),
    )

    return voice


def capture_turn(
    voice: OnlineVoice, config: Dict, wav_path: Optional[str] = None
) -> Dict:
    """麦克风逐轮运行或独立WAV验收，共用既有capture Interface。"""
    source = create_audio_source(
        "wav_file" if wav_path is not None else "microphone",
        input_wav_path=wav_path or "",
        record_executable=config.get("record_executable", "arecord"),
        record_device=config.get("record_device", "default"),
        record_seconds=config.get("record_seconds", 8),
        cancelled=lambda: voice.state == "closed",
    )
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
        return voice.submit_recording(path, direct=wav_path is not None)


def main() -> None:
    """执行一轮真实录音链路，输出结构化回执并关闭在线连接。"""
    parser = argparse.ArgumentParser(description="独立在线WAV验收")
    parser.add_argument("--config", required=True)
    parser.add_argument("--wav", required=True)
    args = parser.parse_args()
    # 1. 外部配置和凭证由组装入口/provider 分别负责。
    config = load_config(args.config)
    voice = create_voice(config)
    try:
        # 2. 真实输入与动作确认后输出，单回合无需唤醒词。
        result = capture_turn(voice, config, args.wav)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if (
            result["status"] != "completed"
            or result.get("tts_status") != "completed"
        ):
            raise SystemExit(1)
    finally:
        # 3. 即使合成失败或 Ctrl-C，也关闭语音资源。
        voice.close()


if __name__ == "__main__":
    main()
