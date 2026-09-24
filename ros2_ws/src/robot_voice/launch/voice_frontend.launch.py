from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("audio_source", default_value="microphone"),
            DeclareLaunchArgument("input_wav_path", default_value=""),
            DeclareLaunchArgument("play_audio", default_value="true"),
            DeclareLaunchArgument("web_audio_enabled", default_value="true"),
            Node(
                package="robot_voice",
                executable="voice_frontend",
                name="voice_frontend",
                output="screen",
                parameters=[
                    {
                        "audio_source": LaunchConfiguration("audio_source"),
                        "input_wav_path": LaunchConfiguration("input_wav_path"),
                        "play_audio": ParameterValue(
                            LaunchConfiguration("play_audio"), value_type=bool
                        ),
                        "web_audio_enabled": ParameterValue(
                            LaunchConfiguration("web_audio_enabled"),
                            value_type=bool,
                        ),
                    }
                ],
            )
        ]
    )
