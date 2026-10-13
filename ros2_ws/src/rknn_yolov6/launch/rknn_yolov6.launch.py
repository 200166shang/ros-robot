"""从 detector 包配置启动 YOLOv6 ROS 节点。"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    """加载 detector YAML 和包内标签文件并构建节点。"""
    package_share = get_package_share_directory('rknn_yolov6')
    config_path = os.path.join(package_share, 'config', 'rknn_yolov6.yaml')
    labels_path = os.path.join(package_share, 'config', 'coco_labels.txt')

    detector_node = Node(
        package='rknn_yolov6',
        executable='rknn_yolov6_node',
        name='rknn_yolov6',
        exec_name='tracking:detector',
        output='screen',
        # 标签文件随 Python package 发布，路径由包 share 目录解析。
        parameters=[config_path, {'labels_path': labels_path}],
    )

    return LaunchDescription([detector_node])
