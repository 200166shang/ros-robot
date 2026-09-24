from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory('rknn_yolov6')
    return LaunchDescription([
        DeclareLaunchArgument(
            'model_path',
            default_value='/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn',
            description='Path to the local RKNN model; model weights are not stored in Git.',
        ),
        Node(package='rknn_yolov6', executable='rknn_yolov6_node', output='screen', parameters=[{
            'model_path': LaunchConfiguration('model_path'),
            'labels_path': os.path.join(share, 'config', 'coco_labels.txt'),
            'confidence_threshold': 0.30,
            'nms_threshold': 0.30,
        }])
    ])
