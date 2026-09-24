from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='usb_camera',
            executable='usb_camera_node',
            name='usb_camera',
            output='screen',
            parameters=[{
                'device': '/dev/video0',
                'width': 1280,
                'height': 720,
                'fps': 30,
                'lazy': True,
            }],
        )
    ])
