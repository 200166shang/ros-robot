"""Start the browser-rendered head simulator without physical peripherals."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Launch only the simulation backend, Agent command gateway, and web UI."""
    web_port = ParameterValue(
        LaunchConfiguration('web_port'),
        value_type=int,
    )
    return LaunchDescription([
        DeclareLaunchArgument(
            'web_port',
            default_value='8080',
            description='Loopback-only HTTP port for the Mac browser tunnel.',
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
        ),
        Node(
            package='web_video_server',
            executable='web_video_node',
            name='web_video_server',
            output='screen',
            parameters=[
                {'host': '127.0.0.1', 'port': web_port},
            ],
        ),
    ])
