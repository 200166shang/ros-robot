from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('frame_divider', default_value='1'),
        Node(
            package='usb_camera',
            executable='usb_camera_node',
            name='usb_camera',
            output='screen',
            parameters=[{
                'device_candidates': ['/dev/video0'],
                'width': 1280,
                'height': 720,
                'fps': 30,
                'frame_divider': LaunchConfiguration('frame_divider'),
                'lazy': True,
            }],
        )
    ])
