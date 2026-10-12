from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
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
            'lidar_to_camera_x': 0.20,
            'lidar_to_camera_y': 0.0,
            'lidar_to_camera_z': 0.0,
            'lidar_to_camera_roll': 1.5707963267948966,
            'lidar_to_camera_pitch': -1.5707963267948966,
            'lidar_to_camera_yaw': 0.0,
        }])
    ])
