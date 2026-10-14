"""组合固定跟踪与网页控制，可显式启用 Online Agent。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """保留网页设备控制，在线交互使用外部配置，不启动本地模型。"""
    bringup_share = get_package_share_directory("robot_bringup")
    tracking_launch = os.path.join(
        bringup_share, "launch", "tracking.launch.py"
    )
    web_config = os.path.join(bringup_share, "config", "web_video_server.yaml")
    return LaunchDescription(
        [
            DeclareLaunchArgument("with_online_agent", default_value="false"),
            DeclareLaunchArgument("online_config_file", default_value=""),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(tracking_launch),
                launch_arguments={"with_foxglove": "false"}.items(),
            ),
            Node(
                package="web_video_server",
                executable="tracking_control",
                name="tracking_control",
                output="screen",
            ),
            Node(
                package="web_video_server",
                executable="web_video_node",
                name="web_video_server",
                output="screen",
                parameters=[web_config],
            ),
            Node(
                package="robot_agent",
                executable="online_voice_agent",
                name="online_voice_agent",
                output="screen",
                parameters=[
                    {
                        "config_file": LaunchConfiguration(
                            "online_config_file"
                        ),
                    }
                ],
                condition=IfCondition(
                    LaunchConfiguration("with_online_agent")
                ),
            ),
        ]
    )
