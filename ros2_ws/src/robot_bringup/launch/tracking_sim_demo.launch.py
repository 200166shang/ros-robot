"""Closed-loop virtual person tracking with an isolated simulated base."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    web_port = ParameterValue(LaunchConfiguration('web_port'), value_type=int)
    person_enabled = ParameterValue(
        LaunchConfiguration('person_enabled'), value_type=bool)
    return LaunchDescription([
        DeclareLaunchArgument(
            'web_port',
            default_value='8080',
            description='Loopback-only HTTP port used by the Mac SSH tunnel.',
        ),
        DeclareLaunchArgument(
            'person_enabled',
            default_value='true',
            description='Publish the deterministic virtual person detection.',
        ),
        Node(
            package='robot_sim',
            executable='base_sim_node',
            name='robot_base_sim',
            output='screen',
            parameters=[{
                'backend': 'sim',
                'max_linear_mps': 0.25,
                'max_angular_rps': 0.8,
                'command_timeout_sec': 0.5,
                'publish_rate_hz': 30.0,
            }],
        ),
        Node(
            package='robot_sim',
            executable='virtual_person_node',
            name='virtual_person_sim',
            output='screen',
            parameters=[{
                'person_enabled': person_enabled,
                'person_x_m': 2.5,
                'person_y_m': 0.8,
                'image_width': 640,
                'image_height': 360,
                'horizontal_fov_deg': 70.0,
            }],
        ),
        Node(
            package='object_track',
            executable='object_track_node',
            name='simulated_person_tracker',
            output='screen',
            parameters=[{
                'input_topic': '/robot/sim/detections',
                'output_topic': '/robot/sim/tracking_cmd_vel',
                'target_class': 'person',
                'angular_gain': 0.003,
                'max_angular': 0.8,
                'minimum_area': 100,
                'target_timeout_ms': 500,
                'dry_run': False,
            }],
        ),
        Node(
            package='robot_head',
            executable='robot_head_motion',
            name='robot_head_motion',
            output='screen',
            parameters=[{'backend': 'sim'}],
        ),
        Node(
            package='robot_agent',
            executable='command_agent',
            name='command_agent',
            output='screen',
            parameters=[{'simulation_mode': True}],
        ),
        Node(
            package='web_video_server',
            executable='web_video_node',
            name='web_video_server',
            output='screen',
            parameters=[{'host': '127.0.0.1', 'port': web_port}],
        ),
    ])
