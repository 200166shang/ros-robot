"""单独启动 image decoder，并从 img_decode 包内读取默认参数。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """加载 decoder YAML 并创建解码节点。"""
    package_share = get_package_share_directory('img_decode')
    config_path = os.path.join(package_share, 'config', 'img_decode.yaml')

    decoder_node = Node(
        package='img_decode',
        executable='img_decode_node',
        name='img_decode',
        exec_name='tracking:decoder',
        output='screen',
        parameters=[config_path],
    )

    return LaunchDescription([decoder_node])
