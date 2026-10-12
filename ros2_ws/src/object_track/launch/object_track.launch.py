from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='object_track', executable='object_track_node', output='screen', parameters=[{
            'image_topic': '/camera/image_det',
            'dry_run': True,
            'annotated_topic': '/camera/image_det_track',
            'output_topic': '/tracking/cmd_vel_safe',
            'target_class': 'person',
            'angular_gain': 0.01,
            'max_angular': 3.0,
            'minimum_area': 20,
        }])
    ])
