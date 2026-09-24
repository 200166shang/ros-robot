import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    bringup_share = get_package_share_directory('robot_bringup')
    detector_share = get_package_share_directory('rknn_yolov6')
    config = os.path.join(bringup_share, 'config', 'perception.yaml')
    safety_config = os.path.join(
        bringup_share, 'config', 'perception_safety_overrides.yaml')
    detector_parameters = {
        'model_path': LaunchConfiguration('model_path'),
        'labels_path': os.path.join(detector_share, 'config', 'coco_labels.txt'),
    }
    return LaunchDescription([
        DeclareLaunchArgument(
            'model_path',
            default_value='/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn',
            description='Path to the local RKNN model; model weights are not stored in Git.',
        ),
        DeclareLaunchArgument('with_detector', default_value='true'),
        DeclareLaunchArgument('with_agent', default_value='true'),
        DeclareLaunchArgument('with_web', default_value='true'),
        Node(package='usb_camera', executable='usb_camera_node', name='usb_camera',
             output='screen', parameters=[config]),
        Node(package='img_decode', executable='img_decode_node', name='img_decode',
             # C270 MJPEG warnings are noisy; process output remains in the ROS log.
             output='log', parameters=[config]),
        Node(package='rknn_yolov6', executable='rknn_yolov6_node', name='rknn_yolov6',
             output='screen', parameters=[config, detector_parameters],
             condition=IfCondition(LaunchConfiguration('with_detector'))),
        Node(package='object_track', executable='object_track_node', name='object_track',
             output='screen', parameters=[config, safety_config],
             condition=IfCondition(LaunchConfiguration('with_detector'))),
        Node(package='robot_head', executable='robot_head_motion', name='robot_head_motion',
             output='screen', condition=IfCondition(LaunchConfiguration('with_agent'))),
        Node(package='robot_agent', executable='command_agent', name='command_agent',
             output='screen', condition=IfCondition(LaunchConfiguration('with_agent'))),
        Node(package='web_video_server', executable='web_video_node', name='web_video_server',
             output='screen', parameters=[config, safety_config],
             condition=IfCondition(LaunchConfiguration('with_web'))),
    ])
