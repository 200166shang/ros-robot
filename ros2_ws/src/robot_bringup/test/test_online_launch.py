"""验证完整在线入口沿用固定跟踪组合与安全启动参数。"""

import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


@pytest.fixture
def ros_launch_loop():
    """Foxy LaunchContext要求当前事件循环，由测试明确创建并释放。"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def test_online_launch_composes_one_complete_agent_with_tracking(
    ros_launch_loop,
) -> None:
    """统一启动仅有一个在线入口，默认关闭可视化，Agent无需运行模式参数。"""
    source = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location(
        "online_launch", source / "launch" / "online_agent.launch.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with patch.object(
        module, "get_package_share_directory", return_value=str(source)
    ):
        description = module.generate_launch_description()

    declarations = {
        action.name: action
        for action in description.entities
        if isinstance(action, DeclareLaunchArgument)
    }
    assert set(declarations) == {"config_file", "with_foxglove"}
    assert declarations["config_file"].default_value is None
    assert declarations["with_foxglove"].default_value[0].text == "false"
    includes = [
        action
        for action in description.entities
        if isinstance(action, IncludeLaunchDescription)
    ]
    assert len(includes) == 1
    assert includes[0].condition is None
    with patch(
        "ament_index_python.packages.get_package_share_directory",
        side_effect=lambda package: str(source.parent / package),
    ):
        includes[0].launch_description_source.get_launch_description(
            LaunchContext()
        )
    assert includes[0].launch_description_source.location.endswith(
        "launch/tracking.launch.py"
    )
    assert isinstance(
        dict(includes[0].launch_arguments)["with_foxglove"],
        LaunchConfiguration,
    )
    nodes = [
        action for action in description.entities if isinstance(action, Node)
    ]
    assert len(nodes) == 1
    agent = nodes[0]
    assert agent.condition is None
    assert "online_voice_agent" in agent.cmd[0][0].describe()
