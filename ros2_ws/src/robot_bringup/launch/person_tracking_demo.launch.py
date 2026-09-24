"""Composable one-shot voice-to-person-tracking demo.

The launch file composes existing package launch files. It does not duplicate
camera, decoder, detector, tracker, Agent, or voice node implementations.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    bringup_share = get_package_share_directory("robot_bringup")
    voice_share = get_package_share_directory("robot_voice")
    perception_launch = os.path.join(
        bringup_share, "launch", "perception.launch.py"
    )
    voice_launch = os.path.join(voice_share, "launch", "voice_frontend.launch.py")
    local_voice_fixture = (
        "/home/orangepi/local-data/ros-robot/voice-fixtures/"
        "start_person_tracking_zh_2026-09-24.wav"
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "audio_source",
                default_value="wav_file",
                description="Use the local deterministic sample by default; microphone is opt-in.",
            ),
            DeclareLaunchArgument(
                "input_wav_path",
                default_value=local_voice_fixture,
                description="Local, untracked WAV fixture used when audio_source=wav_file.",
            ),
            DeclareLaunchArgument(
                "model_path",
                default_value="/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn",
                description="Path to the local RKNN model; model weights are not stored in Git.",
            ),
            DeclareLaunchArgument("run_acceptance_probe", default_value="true"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(perception_launch),
                launch_arguments={
                    "with_detector": "true",
                    "with_agent": "true",
                    "with_web": "true",
                    "model_path": LaunchConfiguration("model_path"),
                }.items(),
            ),
            Node(
                package="robot_agent",
                executable="llm_ros_node",
                name="qwen_ros_bridge",
                output="screen",
                parameters=[{"enable_commands": True}],
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(voice_launch),
                launch_arguments={
                    "audio_source": LaunchConfiguration("audio_source"),
                    "input_wav_path": LaunchConfiguration("input_wav_path"),
                    "play_audio": "false",
                }.items(),
            ),
            Node(
                package="robot_bringup",
                executable="voice_tracking_acceptance_probe.py",
                name="voice_tracking_acceptance_probe",
                output="screen",
                condition=IfCondition(LaunchConfiguration("run_acceptance_probe")),
            ),
        ]
    )
