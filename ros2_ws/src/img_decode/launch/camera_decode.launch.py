from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='usb_camera', executable='usb_camera_node', output='screen', parameters=[{
            'device': '/dev/video0', 'width': 1280, 'height': 720, 'fps': 30, 'lazy': True,
        }]),
        Node(package='img_decode', executable='img_decode_node', output='screen', parameters=[{
            'input_topic': '/image_raw/compressed', 'output_topic': '/camera/image_raw',
            'width': 1280, 'height': 720, 'scale': 0.5, 'frame_divider': 1, 'lazy': True,
        }]),
    ])
