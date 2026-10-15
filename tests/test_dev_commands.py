"""通过项目命令验证显式同步和统一解释器的用户契约。"""

import os
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_absent_environment_requests_explicit_sync(tmp_path):
    """普通命令在环境缺失时提示同步，且不自动创建环境。"""
    shutil.copytree(str(REPO_ROOT / "scripts"), str(tmp_path / "scripts"))
    result = subprocess.run(
        ["bash", str(tmp_path / "scripts/dev.sh"), "python", "-V"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 1
    assert "./scripts/dev.sh sync" in result.stderr
    assert not (tmp_path / ".venv").exists()


@pytest.mark.skipif(
    os.environ.get("ROBOT_TEST_DEPENDENCY_INSTALL") != "1",
    reason="依赖安装验收需要显式 ROBOT_TEST_DEPENDENCY_INSTALL=1",
)
def test_sync_creates_system_compatible_environment_from_lock(tmp_path):
    """新环境从锁文件安装工具，普通执行保持锁文件原样。"""
    shutil.copytree(str(REPO_ROOT / "scripts"), str(tmp_path / "scripts"))
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(str(REPO_ROOT / name), str(tmp_path / name))
    locked = (tmp_path / "uv.lock").read_bytes()
    command = ["bash", str(tmp_path / "scripts/dev.sh")]
    synchronized = subprocess.run(
        command + ["sync"], capture_output=True, text=True
    )
    assert synchronized.returncode == 0, synchronized.stderr
    result = subprocess.run(
        command
        + [
            "python",
            "-c",
            "import sys, cv2, rclpy, flask, websockets; "
            "from importlib.metadata import version; "
            "print(sys.version_info[:2]); print(sys.prefix); "
            "print(sys.base_prefix); print(cv2.__version__); "
            "print(version('sherpa-onnx-bin'))",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "(3, 8)",
        str(tmp_path / ".venv"),
        "/usr",
        "4.2.0",
        "1.13.8",
    ]
    assert (tmp_path / "uv.lock").read_bytes() == locked


def test_colcon_lists_ros_source_packages_without_installing_them():
    """项目构建入口由colcon发现源包，uv不重复安装项目包。"""
    result = subprocess.run(
        [str(REPO_ROOT / "scripts/dev.sh"), "colcon", "list", "--names-only"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    packages = result.stdout.splitlines()
    assert {"robot_agent", "robot_audio", "web_video_server"} <= set(packages)


def test_lint_reports_source_errors_and_accepts_corrected_source(tmp_path):
    """检查入口同时验证格式和静态错误，不修改调用者源码。"""
    source = tmp_path / "example.py"
    source.write_text("print(undefined_name)\n", encoding="utf-8")
    command = [str(REPO_ROOT / "scripts/dev.sh"), "lint", str(source)]
    failed = subprocess.run(command, capture_output=True, text=True)
    assert failed.returncode == 1
    assert "F821" in failed.stdout
    assert source.read_text(encoding="utf-8") == "print(undefined_name)\n"
    source.write_text('print("ready")\n', encoding="utf-8")
    corrected = subprocess.run(command, capture_output=True, text=True)
    assert corrected.returncode == 0, corrected.stdout + corrected.stderr


def test_build_installs_python_node_using_project_interpreter():
    """真实colcon安装脚本使用项目解释器，帮助命令无需音频设备。"""
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts/dev.sh"),
            "build",
            "--packages-select",
            "robot_audio",
            "robot_agent",
            "robot_voice",
            "web_video_server",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    executable = (
        REPO_ROOT
        / "ros2_ws/install/robot_agent/lib/robot_agent/online_voice_wav"
    )
    assert executable.read_text().splitlines()[0] == (
        "#!" + str(REPO_ROOT / ".venv/bin/python")
    )
    helped = subprocess.run(
        [
            str(REPO_ROOT / "scripts/dev.sh"),
            "ros",
            "run",
            "robot_agent",
            "online_voice_wav",
            "--help",
        ],
        capture_output=True,
        text=True,
    )
    assert helped.returncode == 0, helped.stderr
    assert "--config" in helped.stdout


def test_verification_checks_agent_web_and_speech_without_devices():
    """验收命令检查已安装入口与依赖，且无需模型或实际设备。"""
    result = subprocess.run(
        [str(REPO_ROOT / "scripts/dev.sh"), "verify"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "robot_agent" in result.stdout
    assert "web_video_server" in result.stdout
    assert "sherpa-onnx-bin 1.13.8" in result.stdout


def test_local_voice_defaults_use_the_project_speech_executables():
    """语音节点公开参数默认使用统一环境，不再引用旧语音环境。"""
    code = (
        "import rclpy; "
        "from robot_voice.voice_frontend_node import VoiceFrontendNode; "
        "rclpy.init(); node = VoiceFrontendNode(); "
        "print(node.get_parameter('asr_executable').value); "
        "print(node.get_parameter('tts_executable').value); "
        "node.destroy_node(); rclpy.shutdown()"
    )
    result = subprocess.run(
        [str(REPO_ROOT / "scripts/dev.sh"), "python", "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (
        str(REPO_ROOT / ".venv/bin/sherpa-onnx") in result.stdout.splitlines()
    )
    assert str(REPO_ROOT / ".venv/bin/sherpa-onnx-offline-tts") in (
        result.stdout.splitlines()
    )


@pytest.mark.parametrize(
    "entry_point", [("dev.sh", "test-ros"), ("colcon.sh", "test")]
)
def test_ros_workspace_discovers_pytest_function_cases(entry_point, tmp_path):
    """ROS测试入口执行函数式音频测试，不能只发现unittest类。"""
    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / entry_point[0]),
            entry_point[1],
            "--packages-select",
            "robot_audio",
            "--test-result-base",
            str(tmp_path),
            "--executor",
            "sequential",
            "--event-handlers",
            "console_direct+",
            "--pytest-args",
            "-q",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = ElementTree.parse(tmp_path / "robot_audio/pytest.xml").getroot()
    cases = {case.attrib["name"]: case for case in report.iter("testcase")}
    representative_cases = {
        "test_cancelled_audio_process_is_reaped[record]",
        "test_partial_pcm_frames_and_idle_close_reap_process",
    }
    assert representative_cases <= cases.keys()
    assert all(
        cases[name].find("skipped") is None for name in representative_cases
    )
    assert report.find(".//failure") is None
    assert report.find(".//error") is None
