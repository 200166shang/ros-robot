from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='img_encode',
            executable='img_encode_node',
            name='img_encode',
            output='screen',
            parameters=[{
                'input_topic': '/camera/image_raw',
                'output_topic': '/camera/image_raw/compressed',
                'jpeg_quality': 80,
            }],
        ),
    ])
