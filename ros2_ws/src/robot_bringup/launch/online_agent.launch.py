"""统一启动完整在线交互和固定感知组合，保持无物理动作输出。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """外部配置为必填项；复用 Launch 生命周期及既有感知前提。"""
    tracking = os.path.join(
        get_package_share_directory("robot_bringup"),
        "launch",
        "tracking.launch.py",
    )
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "config_file",
                description="External online JSON configuration.",
            ),
            DeclareLaunchArgument("with_foxglove", default_value="false"),
            # 1. 固定感知组合自行管理依赖，Follow/融合默认待机。
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(tracking),
                launch_arguments={
                    "with_foxglove": LaunchConfiguration("with_foxglove")
                }.items(),
            ),
            # 2. 一个入口统一文本、录音、可选麦克风、感知和记忆。
            Node(
                package="robot_agent",
                executable="online_voice_agent",
                name="online_voice_agent",
                output="screen",
                parameters=[
                    {
                        "config_file": LaunchConfiguration("config_file"),
                    }
                ],
            ),
        ]
    )
