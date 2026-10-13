"""从所属包 YAML 启动 ObjectTrack 节点。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """加载跟踪参数并创建节点。"""
    package_share = get_package_share_directory('object_track')
    config_path = os.path.join(package_share, 'config', 'object_track.yaml')
    tracker_node = Node(
        package='object_track',
        executable='object_track_node',
        name='object_track',
        exec_name='tracking:tracker',
        output='screen',
        parameters=[config_path],
    )
    return LaunchDescription([tracker_node])
