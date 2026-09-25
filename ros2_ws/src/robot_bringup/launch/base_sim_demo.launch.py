"""Start only the isolated differential-drive simulator and browser UI."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    web_port = ParameterValue(LaunchConfiguration('web_port'), value_type=int)
    return LaunchDescription([
        DeclareLaunchArgument(
            'web_port',
            default_value='8080',
            description='Loopback-only HTTP port used by the Mac SSH tunnel.',
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
            package='web_video_server',
            executable='web_video_node',
            name='web_video_server',
            output='screen',
            parameters=[{'host': '127.0.0.1', 'port': web_port}],
        ),
    ])
