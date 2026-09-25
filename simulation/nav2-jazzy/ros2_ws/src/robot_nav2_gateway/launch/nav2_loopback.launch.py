import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    nav2_bringup = get_package_share_directory("nav2_bringup")
    loopback_launch = os.path.join(
        nav2_bringup, "launch", "tb3_loopback_simulation.launch.py"
    )
    use_rviz = LaunchConfiguration("use_rviz")
    return LaunchDescription([
        DeclareLaunchArgument(
            "use_rviz",
            default_value="False",
            description="RViz is disabled; the Mac browser renders the map.",
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(loopback_launch),
            launch_arguments={"use_rviz": use_rviz}.items(),
        ),
        Node(
            package="robot_nav2_gateway",
            executable="nav2_http_gateway",
            name="robot_nav2_http_gateway",
            output="screen",
            parameters=[{"use_sim_time": True, "http_port": 18091}],
        ),
    ])
