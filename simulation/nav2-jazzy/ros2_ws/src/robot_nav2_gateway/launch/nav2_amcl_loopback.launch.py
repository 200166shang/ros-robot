import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    bringup_dir = get_package_share_directory("nav2_bringup")
    sim_dir = get_package_share_directory("nav2_minimal_tb3_sim")
    map_file = LaunchConfiguration("map")
    params_file = LaunchConfiguration("params_file")
    remappings = [("/tf", "tf"), ("/tf_static", "tf_static")]

    with open(os.path.join(sim_dir, "urdf", "turtlebot3_waffle.urdf"),
              "r", encoding="utf-8") as urdf_file:
        robot_description = urdf_file.read()

    return LaunchDescription([
        DeclareLaunchArgument(
            "map",
            default_value=os.path.join(bringup_dir, "maps", "tb3_sandbox.yaml"),
            description="Known static map used by map_server and AMCL.",
        ),
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(bringup_dir, "params", "nav2_params.yaml"),
            description="Upstream Nav2 parameters for the TurtleBot3 loopback profile.",
        ),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            output="screen",
            parameters=[{"use_sim_time": True, "robot_description": robot_description}],
            remappings=remappings,
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(bringup_dir, "launch", "bringup_launch.py")
            ),
            launch_arguments={
                "namespace": "",
                "use_namespace": "false",
                "map": map_file,
                "use_sim_time": "True",
                "params_file": params_file,
                "autostart": "true",
                "use_composition": "True",
                "use_respawn": "False",
                "use_localization": "True",
            }.items(),
        ),
        Node(
            package="nav2_loopback_sim",
            executable="loopback_simulator",
            name="loopback_simulator",
            output="screen",
            parameters=[
                params_file,
                {
                    "scan_frame_id": "base_scan",
                    "publish_map_odom_tf": False,
                },
            ],
            remappings=remappings,
        ),
        Node(
            package="robot_nav2_gateway",
            executable="nav2_http_gateway",
            name="robot_nav2_http_gateway",
            output="screen",
            parameters=[
                {
                    "use_sim_time": True,
                    "http_port": 18091,
                    "simulation_mode": "amcl",
                    "locations_file": "locations.json",
                }
            ],
        ),
    ])
