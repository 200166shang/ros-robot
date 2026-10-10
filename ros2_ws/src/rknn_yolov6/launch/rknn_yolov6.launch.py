import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


# 声明检测节点所需的外部资源、话题和运行模式参数。
def generate_launch_description():
    share = get_package_share_directory('rknn_yolov6')
    arguments = [
        DeclareLaunchArgument(
            'model_path',
            default_value='/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn',
            description='Path to the local RKNN model; model weights are not stored in Git.',
        ),
        DeclareLaunchArgument(
            'haar_cascade_path',
            default_value='',
            description='External Haar cascade path for the non-ARM fallback.',
        ),
        DeclareLaunchArgument('input_topic', default_value='/camera/image_raw'),
        DeclareLaunchArgument('detections_topic', default_value='/ai_msg_det'),
        DeclareLaunchArgument('annotated_topic', default_value='/camera/image_det'),
        DeclareLaunchArgument('confidence_threshold', default_value='0.30'),
        DeclareLaunchArgument('nms_threshold', default_value='0.30'),
        DeclareLaunchArgument('enabled', default_value='true'),
        DeclareLaunchArgument('always_process', default_value='false'),
        DeclareLaunchArgument('print_perf_detail', default_value='false'),
        DeclareLaunchArgument('use_multi_npu_core', default_value='false'),
        DeclareLaunchArgument('is_offline_image_mode', default_value='false'),
        DeclareLaunchArgument('offline_images_path', default_value=''),
        DeclareLaunchArgument('offline_output_path', default_value=''),
    ]

    detector = Node(
        package='rknn_yolov6',
        executable='rknn_yolov6_node',
        name='rknn_yolov6',
        output='screen',
        parameters=[{
            'model_path': LaunchConfiguration('model_path'),
            'labels_path': os.path.join(share, 'config', 'coco_labels.txt'),
            'haar_cascade_path': LaunchConfiguration('haar_cascade_path'),
            'input_topic': LaunchConfiguration('input_topic'),
            'detections_topic': LaunchConfiguration('detections_topic'),
            'annotated_topic': LaunchConfiguration('annotated_topic'),
            'confidence_threshold': ParameterValue(LaunchConfiguration('confidence_threshold'), value_type=float),
            'nms_threshold': ParameterValue(LaunchConfiguration('nms_threshold'), value_type=float),
            'enabled': ParameterValue(LaunchConfiguration('enabled'), value_type=bool),
            'always_process': ParameterValue(LaunchConfiguration('always_process'), value_type=bool),
            'print_perf_detail': ParameterValue(LaunchConfiguration('print_perf_detail'), value_type=bool),
            'use_multi_npu_core': ParameterValue(LaunchConfiguration('use_multi_npu_core'), value_type=bool),
            'is_offline_image_mode': ParameterValue(
                LaunchConfiguration('is_offline_image_mode'), value_type=bool),
            'offline_images_path': LaunchConfiguration('offline_images_path'),
            'offline_output_path': LaunchConfiguration('offline_output_path'),
        }],
    )

    return LaunchDescription(arguments + [detector])
