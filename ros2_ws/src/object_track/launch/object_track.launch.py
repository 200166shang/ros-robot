from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='object_track', executable='object_track_node', output='screen', parameters=[{
            'dry_run': True,
            'output_topic': '/tracking/cmd_vel_safe',
            'target_class': 'person',
            'angular_gain': 0.003,
            'max_angular': 1.0,
        }])
    ])
