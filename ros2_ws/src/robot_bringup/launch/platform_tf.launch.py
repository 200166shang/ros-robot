"""从 bringup 平台配置发布 camera 与 laser 间的静态变换。"""

import os
from typing import Any, Dict

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def _load_platform_config(config_path: str) -> Dict[str, Any]:
    """读取平台 frame 与静态外参默认值。"""
    with open(config_path, 'r') as config_file:
        return yaml.safe_load(config_file)['tracking_platform']


def generate_launch_description() -> LaunchDescription:
    """读取平台 YAML 并构建静态 TF 节点。"""
    bringup_share = get_package_share_directory('robot_bringup')
    config_path = os.path.join(bringup_share, 'config', 'platform.yaml')
    platform_config = _load_platform_config(config_path)
    laser_to_camera = platform_config['laser_to_camera']

    # tf2_ros 按 x/y/z/yaw/pitch/roll 接收变换，
    # 最后两个参数依次是 parent 和 child frame。
    transform_arguments = [
        str(laser_to_camera['x']),
        str(laser_to_camera['y']),
        str(laser_to_camera['z']),
        str(laser_to_camera['yaw']),
        str(laser_to_camera['pitch']),
        str(laser_to_camera['roll']),
        platform_config['camera_frame'],
        platform_config['laser_frame'],
    ]
    static_transform_node = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='lidar_camera_static_transform',
        exec_name='tracking:platform_tf',
        arguments=transform_arguments,
        output='screen',
    )

    return LaunchDescription([static_transform_node])
