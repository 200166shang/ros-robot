"""验证单一跟踪组合的 Launch 接口和模块清单。"""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch_ros.actions import Node


SOURCE_ROOT = Path(__file__).parents[2]


def _load_launch_module(module_name: str, path: Path):
    """按路径加载 Launch 模块，便于直接检查其公开描述。"""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load launch module: {}".format(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TrackingLaunchTest(unittest.TestCase):
    """验证固定模块组合、不暴露 mode 且不含自定义监督动作。"""

    def test_tracking_launch_starts_all_core_modules_without_mode(self) -> None:
        launch_path = SOURCE_ROOT / "robot_bringup" / "launch" / "tracking.launch.py"
        module = _load_launch_module("tracking_launch_under_test", launch_path)
        included_modules = []
        include_package_launch = module._include_package_launch

        def record_include(package_name, launch_file):
            included_modules.append((package_name, launch_file))
            return include_package_launch(package_name, launch_file)

        with patch.object(
            module,
            "get_package_share_directory",
            side_effect=lambda package: str(SOURCE_ROOT / package),
        ), patch.object(
            module,
            "_include_package_launch",
            side_effect=record_include,
        ):
            description = module.generate_launch_description()

        declarations = [
            action
            for action in description.entities
            if isinstance(action, DeclareLaunchArgument)
        ]
        self.assertEqual(
            [argument.name for argument in declarations], ["with_foxglove"]
        )
        self.assertEqual(declarations[0].default_value[0].text, "true")
        self.assertEqual(
            included_modules,
            [
                ("usb_camera", "usb_camera.launch.py"),
                ("img_decode", "img_decode.launch.py"),
                ("rknn_yolov6", "rknn_yolov6.launch.py"),
                ("ydlidar", "ydlidar.launch.py"),
                ("robot_bringup", "platform_tf.launch.py"),
                ("object_track", "object_track.launch.py"),
            ],
        )

        includes = [
            action
            for action in description.entities
            if isinstance(action, IncludeLaunchDescription)
        ]
        self.assertEqual(len(includes), 6)
        self.assertTrue(all(include.condition is None for include in includes))
        self.assertTrue(all(include.launch_arguments == () for include in includes))
        self.assertEqual(
            sum(isinstance(action, Node) for action in description.entities),
            1,
        )
        self.assertEqual(
            {type(action) for action in description.entities},
            {DeclareLaunchArgument, IncludeLaunchDescription, Node},
        )

    def test_object_track_launch_has_no_mode_argument(self) -> None:
        launch_path = SOURCE_ROOT / "object_track" / "launch" / "object_track.launch.py"
        module = _load_launch_module("object_track_launch_under_test", launch_path)
        with patch.object(
            module,
            "get_package_share_directory",
            return_value=str(SOURCE_ROOT / "object_track"),
        ):
            description = module.generate_launch_description()

        self.assertFalse(
            any(
                isinstance(action, DeclareLaunchArgument)
                for action in description.entities
            )
        )
        self.assertEqual(len(description.entities), 1)
        self.assertIsInstance(description.entities[0], Node)

    def test_person_demo_does_not_forward_mode(self) -> None:
        launch_path = (
            SOURCE_ROOT
            / "robot_bringup"
            / "launch"
            / "person_tracking_demo.launch.py"
        )
        module = _load_launch_module("person_demo_launch_under_test", launch_path)
        package_paths = {
            "robot_bringup": str(SOURCE_ROOT / "robot_bringup"),
            "robot_voice": str(SOURCE_ROOT / "robot_voice"),
        }
        with patch.object(
            module,
            "get_package_share_directory",
            side_effect=lambda package: package_paths[package],
        ):
            description = module.generate_launch_description()

        tracking_includes = [
            action
            for action in description.entities
            if isinstance(action, IncludeLaunchDescription)
            and dict(action.launch_arguments) == {"with_foxglove": "false"}
        ]
        self.assertEqual(len(tracking_includes), 1)
        executables = [
            "".join(part.describe() for part in action.cmd[0])
            for action in description.entities
            if isinstance(action, Node)
        ]
        self.assertEqual(len(executables), 3)
        for expected, command in zip(
            ["tracking_control", "web_video_node", "online_agent"], executables
        ):
            self.assertIn(expected, command)
