"""在线交互共同组装：读取外部配置，集中解释依赖和默认值。"""

import json
from pathlib import Path
from typing import Callable, Dict, Optional, Union

from robot_agent.actions.capabilities import (
    ActionCapabilities,
    create_default_actions,
)
from robot_agent.actions.registry import ActionRegistry
from robot_agent.application import AgentApplication
from robot_agent.conversation.agent import Agent
from robot_agent.conversation.memory import ConversationMemory
from robot_agent.conversation.provider import DashScopeProvider
from robot_agent.legacy_io import SpeechInput
from robot_agent.voice.live_input import LiveSpeechInput
from robot_agent.voice.speech import DashScopeASR, DashScopeTTS
from robot_audio.audio_io import play_wav
from robot_audio.pcm_input import PcmMicrophone

DEFAULT_ACTION_TIMEOUT = 5.0


def load_config(filename: Union[str, Path]) -> Dict:
    """读取源码外JSON对象；文件、语法和形状错误直接向调用者显露。"""
    config = json.loads(
        Path(filename).expanduser().read_text(encoding="utf-8")
    )
    if not isinstance(config, dict):
        raise ValueError("在线配置必须是JSON对象")
    return config


def build_agent(
    config: Dict, actions: Optional[ActionRegistry] = None
) -> Agent:
    """组装同一交互Implementation；文本测试直接调用，无ROS文本入口。"""
    if actions is None:
        actions = create_default_actions().registry
    return Agent(
        DashScopeProvider(config),
        actions,
        provider_timeout=float(config.get("provider_timeout", 60)),
        action_timeout=float(
            config.get("action_timeout", DEFAULT_ACTION_TIMEOUT)
        ),
        memory=ConversationMemory(
            Path(
                config.get(
                    "memory_file",
                    "~/.local/state/ros-robot/conversation-summary.json",
                )
            ),
            recent_turns=config.get("memory_recent_turns", 6),
            summary_trigger=config.get("memory_summary_trigger", 6),
        ),
    )


def build_application(
    config: Dict,
    capabilities: Optional[ActionCapabilities] = None,
    speech_input: Optional[SpeechInput] = None,
    *,
    input_mode: str = "recording",
) -> AgentApplication:
    """组装已有文本/动作和语音 Adapters；始终保持缺失设备模拟。"""
    directory = Path(config["output_dir"]).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[4]
    if directory == checkout or checkout in directory.parents:
        raise ValueError("output_dir 必须在源码目录外")
    if capabilities is None:
        capabilities = create_default_actions()
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

    recognize = None
    if speech_input is None:
        if input_mode == "microphone":
            speech_input = LiveSpeechInput(
                config,
                PcmMicrophone(
                    config.get("record_executable", "arecord"),
                    config.get("record_device", "default"),
                ),
            )
        elif input_mode == "recording":
            recording_input = DashScopeASR(config)
            speech_input = recording_input
            recognize = recording_input.recognize
        else:
            raise ValueError("未知语音输入模式")

    voice = AgentApplication(
        build_agent(config, capabilities.registry),
        speech_input,
        DashScopeTTS(config),
        directory,
        music_playing=capabilities.music_playing,
        playback=playback,
        silence_timeout=float(config.get("silence_timeout", 120)),
        speech_timeout=float(config.get("speech_timeout", 60)),
        tts_attempts=int(config.get("tts_attempts", 3)),
        failure_threshold=int(config.get("tts_failure_threshold", 5)),
        retry_delay=float(config.get("tts_retry_delay", 1)),
        recognize_recording=recognize,
    )

    return voice
