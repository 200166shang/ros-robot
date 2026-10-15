"""验收板端解释器、已安装节点和语音工具，绝不启动实际设备。"""

import importlib
import shutil
import subprocess
import sys
from importlib.metadata import distribution, version
from pathlib import Path

from ament_index_python.packages import get_package_prefix

PACKAGE_EXECUTABLES = {
    "robot_agent": ("online_voice_agent", "online_voice_wav"),
    "robot_voice": ("voice_frontend",),
    "web_video_server": ("web_video_node", "tracking_control"),
}


def main() -> None:
    """通过实际安装脚本和动态链接检查依赖，不读取模型或凭证。"""
    root = Path(__file__).resolve().parents[1]
    interpreter = root / ".venv/bin/python"
    assert sys.executable == str(interpreter), sys.executable
    assert sys.version_info[:2] == (3, 8), sys.version
    assert sys.base_prefix == "/usr", sys.base_prefix
    print("Python", sys.version.split()[0], sys.executable)

    # 1. 导入系统二进制扩展，确认 ROS 与 OpenCV 保持相同 ABI。
    for name in (
        "rclpy",
        "cv2",
        "numpy",
        "flask",
        "websocket",
        "pydantic",
        "httpx",
        "websockets",
    ):
        module = importlib.import_module(name)
        print(name, module.__file__)
    for name in (
        "Flask",
        "websocket-client",
        "sherpa-onnx-bin",
        "pydantic",
        "pydantic-core",
        "httpx",
        "websockets",
        "httpcore",
    ):
        installed = distribution(name)
        assert root / ".venv" in installed.locate_file("").parents
        print(name, version(name))

    # 2. 加载真实 console_scripts 目标，并逐一检查安装脚本 shebang。
    for package, names in PACKAGE_EXECUTABLES.items():
        prefix = Path(get_package_prefix(package))
        assert root / "ros2_ws/install" in prefix.parents, prefix
        entry_points = {
            entry.name: entry
            for entry in distribution(package).entry_points
            if entry.group == "console_scripts"
        }
        for name in names:
            executable = prefix / "lib" / package / name
            assert executable.read_text().splitlines()[0] == (
                "#!" + str(interpreter)
            ), executable
            entry_points[name].load()
            print(package, name, executable)

    subprocess.run(
        [
            str(
                root
                / "ros2_ws/install/robot_agent/lib/robot_agent"
                / "online_voice_wav"
            ),
            "--help",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    # 3. 原生 sherpa 工具只运行版本/帮助入口，以验证 ARM64 动态库。
    for name in ("sherpa-onnx", "sherpa-onnx-offline-tts"):
        executable = root / ".venv/bin" / name
        assert shutil.which(name) == str(executable), executable
        subprocess.run(
            [str(executable), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        print(name, executable)
    subprocess.run([str(root / ".venv/bin/sherpa-onnx-version")], check=True)


if __name__ == "__main__":
    main()
