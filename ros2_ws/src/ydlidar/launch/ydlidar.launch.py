from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    config = os.path.join(
        get_package_share_directory('ydlidar'), 'config', 'ydlidar.yaml')
    return LaunchDescription([
        DeclareLaunchArgument(
            'port',
            default_value='/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0',
            description='YDLIDAR USB serial device'),
        DeclareLaunchArgument('lidar_frame', default_value='laser_link'),
        Node(
            package='ydlidar',
            executable='ydlidar_node',
            name='ydlidar',
            output='screen',
            parameters=[config, {
                'port': LaunchConfiguration('port'),
                'frame_id': LaunchConfiguration('lidar_frame'),
            }],
        ),
    ])
