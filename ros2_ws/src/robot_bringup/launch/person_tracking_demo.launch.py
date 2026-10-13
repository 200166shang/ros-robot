"""组合基础视觉跟踪、语音 Agent 与 Web 视频服务的演示入口。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """声明演示参数，并组合跟踪、Agent、Web 和语音节点。"""
    bringup_share = get_package_share_directory('robot_bringup')
    voice_share = get_package_share_directory('robot_voice')
    tracking_launch = os.path.join(bringup_share, 'launch', 'tracking.launch.py')
    web_config = os.path.join(bringup_share, 'config', 'web_video_server.yaml')
    voice_launch = os.path.join(voice_share, 'launch', 'voice_frontend.launch.py')
    local_voice_fixture = (
        '/home/orangepi/local-data/ros-robot/voice-fixtures/'
        'start_person_tracking_zh_2026-09-24.wav'
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'audio_source',
                default_value='wav_file',
                description=(
                    '默认使用本地 WAV 样例；麦克风输入需显式选择。'
                ),
            ),
            DeclareLaunchArgument(
                'input_wav_path',
                default_value=local_voice_fixture,
                description='audio_source=wav_file 时使用的本地样例路径。',
            ),
            DeclareLaunchArgument('run_acceptance_probe', default_value='true'),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(tracking_launch),
                launch_arguments={
                    'with_foxglove': 'false',
                }.items(),
            ),
            Node(
                package='robot_agent',
                executable='command_agent',
                name='command_agent',
                output='screen',
            ),
            Node(
                package='web_video_server',
                executable='web_video_node',
                name='web_video_server',
                output='screen',
                parameters=[web_config],
            ),
            Node(
                package='robot_agent',
                executable='llm_ros_node',
                name='qwen_ros_bridge',
                output='screen',
                parameters=[{'enable_commands': True}],
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(voice_launch),
                launch_arguments={
                    'audio_source': LaunchConfiguration('audio_source'),
                    'input_wav_path': LaunchConfiguration('input_wav_path'),
                    'play_audio': 'false',
                }.items(),
            ),
            Node(
                package='robot_bringup',
                executable='voice_tracking_acceptance_probe.py',
                name='voice_tracking_acceptance_probe',
                output='screen',
                condition=IfCondition(LaunchConfiguration('run_acceptance_probe')),
            ),
        ]
    )
