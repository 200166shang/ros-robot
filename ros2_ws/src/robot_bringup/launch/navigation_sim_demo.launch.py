"""Text/Qwen-to-Nav2 prototype with all navigation confined to simulation."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    web_port = ParameterValue(LaunchConfiguration("web_port"), value_type=int)
    return LaunchDescription([
        DeclareLaunchArgument(
            "llama_endpoint",
            default_value="http://127.0.0.1:18080/completion",
            description="Board-local llama-server completion endpoint.",
        ),
        DeclareLaunchArgument(
            "nav2_http_endpoint",
            default_value="http://127.0.0.1:18092",
            description="Loopback-only endpoint made available by the Mac reverse tunnel.",
        ),
        DeclareLaunchArgument(
            "web_port",
            default_value="8080",
            description="Board-local browser console port forwarded by open-nav-sim.sh.",
        ),
        Node(
            package="robot_agent",
            executable="command_agent",
            name="command_agent",
            output="screen",
            parameters=[{
                "simulation_mode": True,
                "enable_simulated_navigation": True,
                "nav2_http_endpoint": LaunchConfiguration("nav2_http_endpoint"),
                "navigation_http_timeout_seconds": 2.0,
            }],
        ),
        Node(
            package="robot_agent",
            executable="llm_ros_node",
            name="qwen_ros_bridge",
            output="screen",
            parameters=[{
                "llama_endpoint": LaunchConfiguration("llama_endpoint"),
                "enable_commands": False,
                "enable_simulated_navigation": True,
                "command_timeout_seconds": 5.0,
            }],
        ),
        Node(
            package="web_video_server",
            executable="web_video_node",
            name="web_video_server",
            output="screen",
            parameters=[{"host": "127.0.0.1", "port": web_port}],
        ),
    ])
