from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


# 独立启动跟踪器：先发布可配置的 camera <- laser 静态 TF，再启动读取该 TF 的节点。
def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('camera_frame', default_value='camera'),
        DeclareLaunchArgument('laser_frame', default_value='laser_link'),
        DeclareLaunchArgument('lidar_camera_x', default_value='0.20'),
        DeclareLaunchArgument('lidar_camera_y', default_value='0.0'),
        DeclareLaunchArgument('lidar_camera_z', default_value='0.0'),
        DeclareLaunchArgument('lidar_camera_yaw', default_value='0.0'),
        DeclareLaunchArgument('lidar_camera_pitch', default_value='-1.5707963267948966'),
        DeclareLaunchArgument('lidar_camera_roll', default_value='1.5707963267948966'),
        Node(package='tf2_ros', executable='static_transform_publisher', name='lidar_camera_static_transform',
             arguments=[LaunchConfiguration('lidar_camera_x'), LaunchConfiguration('lidar_camera_y'),
                        LaunchConfiguration('lidar_camera_z'), LaunchConfiguration('lidar_camera_yaw'),
                        LaunchConfiguration('lidar_camera_pitch'), LaunchConfiguration('lidar_camera_roll'),
                        LaunchConfiguration('camera_frame'), LaunchConfiguration('laser_frame')],
             output='screen'),
        Node(package='object_track', executable='object_track_node', output='screen', parameters=[{
            'image_topic': '/camera/image_det',
            'dry_run': True,
            'annotated_topic': '/camera/image_det_track',
            'output_topic': '/tracking/cmd_vel_safe',
            'lidar_topic': '/scan',
            'target_class': 'person',
            'angular_gain': 0.01,
            'max_angular': 3.0,
            'minimum_area': 20,
            'control_linear': True,
            'linear_gain': 0.5,
            'max_linear': 0.15,
            'keep_distance': 0.3,
            'minimum_range': 0.05,
            'maximum_range': 5.0,
            'camera_fx': 1410.6,
            'camera_fy': 1410.6,
            'camera_cx': 640.0,
            'camera_cy': 360.0,
            'camera_frame': LaunchConfiguration('camera_frame'),
            'laser_frame': LaunchConfiguration('laser_frame'),
            'transform_timeout_sec': 10.0,
        }])
    ])
