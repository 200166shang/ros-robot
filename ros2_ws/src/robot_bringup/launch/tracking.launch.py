"""启动基础跟踪所需的感知节点，并可选启动 Foxglove Bridge。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _include_package_launch(
    package_name: str,
    launch_file: str,
) -> IncludeLaunchDescription:
    """按 package share 路径包含独立模块 Launch。"""
    package_share = get_package_share_directory(package_name)
    launch_path = os.path.join(package_share, 'launch', launch_file)
    return IncludeLaunchDescription(PythonLaunchDescriptionSource(launch_path))


def generate_launch_description() -> LaunchDescription:
    """声明可选可视化并启动固定跟踪组合。"""
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                'with_foxglove',
                default_value='true',
                description='Start the optional Foxglove bridge.',
            ),
            _include_package_launch('usb_camera', 'usb_camera.launch.py'),
            _include_package_launch('img_decode', 'img_decode.launch.py'),
            _include_package_launch('rknn_yolov6', 'rknn_yolov6.launch.py'),
            _include_package_launch('ydlidar', 'ydlidar.launch.py'),
            _include_package_launch('robot_bringup', 'platform_tf.launch.py'),
            _include_package_launch('object_track', 'object_track.launch.py'),
            Node(
                package='foxglove_bridge',
                executable='foxglove_bridge',
                name='foxglove_bridge',
                exec_name='tracking:foxglove',
                output='screen',
                condition=IfCondition(LaunchConfiguration('with_foxglove')),
            ),
        ]
    )
