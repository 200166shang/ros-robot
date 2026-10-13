"""从包内 YAML 启动 YDLIDAR 驱动节点。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """加载驱动配置并构建 YDLIDAR 节点。"""
    package_share = get_package_share_directory('ydlidar')
    config_path = os.path.join(package_share, 'config', 'ydlidar.yaml')

    ydlidar_node = Node(
        package='ydlidar',
        executable='ydlidar_node',
        name='ydlidar',
        exec_name='tracking:ydlidar',
        output='screen',
        parameters=[config_path],
    )

    return LaunchDescription([ydlidar_node])
