"""单独启动相机采集节点，并从 usb_camera 包内读取默认参数。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """加载相机 YAML 并创建采集节点。"""
    package_share = get_package_share_directory('usb_camera')
    config_path = os.path.join(package_share, 'config', 'usb_camera.yaml')

    camera_node = Node(
        package='usb_camera',
        executable='usb_camera_node',
        name='usb_camera',
        exec_name='tracking:camera',
        output='screen',
        parameters=[config_path],
    )

    return LaunchDescription([camera_node])
