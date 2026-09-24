#!/usr/bin/env python3
"""Start the local Qwen service and ROS person-tracking demo on Orange Pi."""

import argparse
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Mapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener


LOGGER = logging.getLogger("demo_launcher")
QWEN_STARTUP_TIMEOUT_SECONDS = 120
QWEN_HEALTH_TIMEOUT_SECONDS = 2
PROCESS_STOP_TIMEOUT_SECONDS = 10
PROCESS_TERM_TIMEOUT_SECONDS = 3
PROCESS_POLL_INTERVAL_SECONDS = 0.2


class DemoError(Exception):
    """A user-actionable error that should stop the demo before unsafe work."""


class ShutdownRequested(Exception):
    """Raised when SIGINT or SIGTERM asks the launcher to stop."""

    def __init__(self, signum: int) -> None:
        super().__init__(signal.Signals(signum).name)
        self.signum = signum


@dataclass(frozen=True)
class DemoConfig:
    """Validated settings for one demo run."""

    project_root: Path
    workspace: Path
    llama_bin: Path
    llama_model: Path
    llama_model_alias: str
    vision_model: Path
    voice_wav: Path
    llama_port: int
    web_port: int
    ros_domain_id: int
    audio_source: str
    run_acceptance_probe: bool
    log_dir: Path


def configure_logging() -> None:
    """Write concise, timestamped phase messages to the foreground terminal."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line interface for the board-side launcher."""
    parser = argparse.ArgumentParser(
        description=(
            "检查本地依赖，启动或复用 Qwen，然后前台运行 "
            "ROS 人物跟踪演示。"
        ),
        epilog=(
            "正式运行按 Ctrl-C 停止 ROS；只会清理由本次启动的 Qwen。"
        ),
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "只检查配置、文件、ROS 环境和端口，"
            "不启动服务或节点。"
        ),
    )
    return parser


def _environment_value(
    environment: Mapping[str, str], key: str, default: str
) -> str:
    """Return an environment override or the documented default."""
    return environment.get(key, default)


def _parse_port(name: str, value: str) -> int:
    """Parse a TCP port and reject values outside the valid port range."""
    if re.fullmatch(r"[0-9]+", value) is None:
        raise DemoError("{} 必须是数字，当前值：{}".format(name, value))

    port = int(value, 10)
    if port < 1 or port > 65535:
        raise DemoError(
            "{} 范围必须是 1–65535，当前值：{}".format(name, value)
        )
    return port


def load_config(
    project_root: Optional[Path] = None,
    environment: Optional[Mapping[str, str]] = None,
) -> DemoConfig:
    """Load settings from environment variables and validate their values."""
    env = os.environ if environment is None else environment
    root = Path(__file__).resolve().parents[1] if project_root is None else project_root
    workspace = root / "ros2_ws"

    llama_port = _parse_port(
        "Qwen 服务端口", _environment_value(env, "DEMO_LLAMA_PORT", "18080")
    )
    web_port = _parse_port(
        "网页服务端口", _environment_value(env, "DEMO_WEB_PORT", "8080")
    )
    if llama_port == web_port:
        raise DemoError("Qwen 服务端口和网页服务端口不能相同。")

    ros_domain_text = _environment_value(env, "ROS_DOMAIN_ID", "74")
    if re.fullmatch(r"[0-9]+", ros_domain_text) is None:
        raise DemoError(
            "ROS_DOMAIN_ID 必须是数字，当前值：{}".format(ros_domain_text)
        )

    audio_source = _environment_value(
        env, "DEMO_AUDIO_SOURCE", "wav_file"
    )
    if audio_source not in ("wav_file", "microphone"):
        raise DemoError(
            "音频来源只能是 wav_file 或 microphone，当前值：{}".format(
                audio_source
            )
        )

    probe_text = _environment_value(
        env, "DEMO_RUN_ACCEPTANCE_PROBE", "true"
    )
    if probe_text not in ("true", "false"):
        raise DemoError(
            "验收探针配置只能是 true 或 false，当前值：{}".format(
                probe_text
            )
        )

    model_alias = _environment_value(
        env, "DEMO_LLAMA_MODEL_ALIAS", "qwen3-robot"
    ).strip()
    if not model_alias.strip():
        raise DemoError("Qwen 模型别名不能为空。")

    return DemoConfig(
        project_root=root,
        workspace=workspace,
        llama_bin=Path(
            _environment_value(
                env,
                "DEMO_LLAMA_BIN",
                "/home/orangepi/build/llama.cpp-qwen3-22cd/bin/"
                "llama-server",
            )
        ),
        llama_model=Path(
            _environment_value(
                env,
                "DEMO_LLAMA_MODEL",
                "/home/orangepi/models/qwen3/qwen3-robot-q8_0.gguf",
            )
        ),
        llama_model_alias=model_alias,
        vision_model=Path(
            _environment_value(
                env,
                "DEMO_VISION_MODEL",
                "/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn",
            )
        ),
        voice_wav=Path(
            _environment_value(
                env,
                "DEMO_INPUT_WAV",
                "/home/orangepi/local-data/ros-robot/voice-fixtures/"
                "start_person_tracking_zh_2026-09-24.wav",
            )
        ),
        llama_port=llama_port,
        web_port=web_port,
        ros_domain_id=int(ros_domain_text, 10),
        audio_source=audio_source,
        run_acceptance_probe=(probe_text == "true"),
        log_dir=Path(
            _environment_value(
                env,
                "DEMO_LOG_DIR",
                "/home/orangepi/local-data/ros-robot/logs",
            )
        ),
    )


def _require_command(command: str, purpose: str) -> None:
    """Fail early with a clear message when a required system command is absent."""
    if shutil.which(command) is None:
        raise DemoError(
            "找不到必要命令：{}。{}".format(command, purpose)
        )


def check_dependencies() -> None:
    """Check external tools needed after ROS environment setup."""
    _require_command("ss", "请确认 iproute2 已安装。")
    _require_command(
        "ros2", "请检查 ROS 2 Foxy 和工作区环境是否已加载。"
    )


def _require_nonempty_file(path: Path, description: str) -> None:
    """Check that a required asset exists and contains data."""
    try:
        is_valid = path.is_file() and path.stat().st_size > 0
    except OSError as error:
        raise DemoError(
            "检查{}失败：{}（{}）".format(description, path, error)
        )
    if not is_valid:
        raise DemoError("{} 不存在或为空：{}".format(description, path))


def check_local_assets(config: DemoConfig) -> None:
    """Check model, workspace, audio, and camera assets without loading them."""
    if not config.llama_bin.is_file() or not os.access(config.llama_bin, os.X_OK):
        raise DemoError(
            "找不到可执行的 llama-server：{}".format(config.llama_bin)
        )

    _require_nonempty_file(config.llama_model, "Qwen 模型文件")
    _require_nonempty_file(config.vision_model, "视觉 RKNN 模型文件")

    foxy_setup = Path("/opt/ros/foxy/setup.bash")
    workspace_setup = config.workspace / "install" / "setup.bash"
    if not foxy_setup.is_file():
        raise DemoError("找不到 ROS 2 Foxy 环境文件：{}".format(foxy_setup))
    if not workspace_setup.is_file():
        raise DemoError(
            "找不到已构建的 ROS 工作区环境文件：{}。"
            "请先构建工作区。".format(workspace_setup)
        )

    if config.audio_source == "wav_file":
        _require_nonempty_file(config.voice_wav, "WAV 测试音频")

    camera = Path("/dev/video0")
    if not camera.exists():
        raise DemoError("找不到摄像头设备：{}".format(camera))


def _urlopen_without_proxy(url: str, timeout: float):
    """Open a local service URL without inheriting external proxy settings."""
    opener = build_opener(ProxyHandler({}))
    return opener.open(url, timeout=timeout)


def http_is_healthy(url: str, timeout: float) -> bool:
    """Return whether a local HTTP endpoint responds successfully."""
    try:
        with _urlopen_without_proxy(url, timeout) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, OSError, ValueError):
        return False


def llama_model_matches(config: DemoConfig) -> bool:
    """Verify that the local llama-server reports the expected model identity."""
    url = "http://127.0.0.1:{}/v1/models".format(config.llama_port)
    try:
        with _urlopen_without_proxy(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ):
        return False

    try:
        models = payload["data"]
        model_ids = {
            item.get("id")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
    except (KeyError, TypeError):
        return False

    expected_ids = {
        config.llama_model_alias,
        str(config.llama_model),
    }
    return not model_ids.isdisjoint(expected_ids)


def port_is_in_use(port: int) -> bool:
    """Check whether any local TCP interface has a listener on this port."""
    try:
        result = subprocess.run(
            ["ss", "-H", "-ltn", "sport = :{}".format(port)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DemoError("检查端口 {} 失败：{}".format(port, error))

    if result.returncode != 0:
        detail = result.stderr.strip() or "ss 命令返回非零状态"
        raise DemoError("检查端口 {} 失败：{}".format(port, detail))
    return bool(result.stdout.strip())


def check_ports_and_model(config: DemoConfig) -> bool:
    """Reject web conflicts and safely identify a reusable Qwen service."""
    if port_is_in_use(config.web_port):
        raise DemoError(
            "网页端口 {} 已有程序监听；可能另一份演示正在运行。"
            "未停止任何进程。".format(config.web_port)
        )

    if not port_is_in_use(config.llama_port):
        return False

    health_url = "http://127.0.0.1:{}/health".format(config.llama_port)
    if not http_is_healthy(health_url, timeout=2):
        raise DemoError(
            "端口 {} 已被占用，但 Qwen 健康检查失败。"
            "未停止任何进程。".format(config.llama_port)
        )

    if not llama_model_matches(config):
        raise DemoError(
            "端口 {} 上的模型无法确认为 '{}'。"
            "为避免误用，未复用或停止该服务。".format(
                config.llama_port, config.llama_model_alias
            )
        )

    LOGGER.info(
        "端口 %s 上运行着预期的 Qwen 模型，将复用该服务。",
        config.llama_port,
    )
    return True


def preflight(config: DemoConfig) -> bool:
    """Run all read-only checks before starting Qwen, ROS, or the camera."""
    LOGGER.info("[1/4] 检查配置值。")
    LOGGER.info("配置值有效。")

    LOGGER.info(
        "[2/4] 检查系统命令、模型文件、ROS 工作区和摄像头。"
    )
    check_dependencies()
    check_local_assets(config)
    LOGGER.info("依赖和本地文件齐备。")

    LOGGER.info("[3/4] 检查 Qwen 与网页端口。")
    qwen_ready = check_ports_and_model(config)
    LOGGER.info("端口状态正常。")

    LOGGER.info("[4/4] ROS 2 环境由 Bash 入口加载。")
    if not os.environ.get("AMENT_PREFIX_PATH"):
        raise DemoError(
            "AMENT_PREFIX_PATH 未设置；请通过 scripts/run-demo.sh 启动，"
            "不要直接运行 Python 文件。"
        )
    LOGGER.info("ROS 环境已加载。")
    return qwen_ready


def report_preflight(config: DemoConfig, qwen_ready: bool) -> None:
    """Explain what a successful check-only run established."""
    qwen_state = (
        "已运行，正式启动时将复用"
        if qwen_ready
        else "尚未运行，正式启动时会启动"
    )
    print()
    print("检查结果：全部通过。")
    print("  Qwen 服务：{}".format(qwen_state))
    print("  ROS_DOMAIN_ID：{}".format(config.ros_domain_id))
    print("  音频来源：{}".format(config.audio_source))
    print(
        "  验收探针：{}".format(
            "true" if config.run_acceptance_probe else "false"
        )
    )
    print("  跟踪安全边界：dry_run=true，不发布底盘运动命令")
    print("只检查模式没有启动 Qwen、ROS 节点或摄像头。")


def _read_log_tail(path: Path, line_count: int = 60) -> str:
    """Read only the end of a potentially large service log."""
    try:
        with path.open("rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            file_size = log_file.tell()
            log_file.seek(max(0, file_size - 65536), os.SEEK_SET)
            content = log_file.read().decode("utf-8", errors="replace")
    except OSError:
        return "无法读取日志文件：{}".format(path)
    lines = content.splitlines()
    return "\n".join(lines[-line_count:])


def _process_group_exists(process: subprocess.Popen) -> bool:
    """Check whether the isolated process group created for a child still exists."""
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _signal_process_group(
    process: subprocess.Popen, signum: int, label: str
) -> None:
    """Send a signal only to a process group created and owned by this launcher."""
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        return
    except OSError as error:
        LOGGER.warning(
            "向本次启动的%s进程组发送%s失败：%s",
            label,
            signal.Signals(signum).name,
            error,
        )


def stop_owned_process(
    process: Optional[subprocess.Popen],
    label: str,
    graceful_timeout: float = PROCESS_STOP_TIMEOUT_SECONDS,
    terminate_timeout: float = PROCESS_TERM_TIMEOUT_SECONDS,
) -> None:
    """Stop one owned process group gracefully, escalating only if necessary."""
    if process is None:
        return

    process.poll()
    if process.returncode is None:
        LOGGER.info("正在请求本次启动的%s正常退出。", label)
        try:
            process.send_signal(signal.SIGINT)
        except OSError:
            pass
    elif _process_group_exists(process):
        # The group leader may have exited while a child it created remains alive.
        _signal_process_group(process, signal.SIGINT, label)

    deadline = time.monotonic() + graceful_timeout
    while time.monotonic() < deadline:
        process.poll()
        if not _process_group_exists(process):
            break
        time.sleep(PROCESS_POLL_INTERVAL_SECONDS)

    if _process_group_exists(process):
        LOGGER.warning(
            "%s未在 %.0f 秒内完全退出，"
            "向本次启动的进程组发送 SIGTERM。",
            label,
            graceful_timeout,
        )
        _signal_process_group(process, signal.SIGTERM, label)
        deadline = time.monotonic() + terminate_timeout
        while time.monotonic() < deadline:
            process.poll()
            if not _process_group_exists(process):
                break
            time.sleep(PROCESS_POLL_INTERVAL_SECONDS)

    if _process_group_exists(process):
        LOGGER.error(
            "%s仍未退出，向本次启动的进程组发送 SIGKILL。", label
        )
        _signal_process_group(process, signal.SIGKILL, label)

    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        LOGGER.error("%s 主进程尚未回收。", label)


class ShutdownController:
    """Track shutdown requests and forward them only to the active ROS launcher."""

    def __init__(self) -> None:
        self.requested_signal: Optional[int] = None
        self.qwen_process: Optional[subprocess.Popen] = None
        self.ros_process: Optional[subprocess.Popen] = None

    def handle_signal(self, signum: int, _frame: object) -> None:
        """Record a terminal signal and ask an active ROS launch to stop cleanly."""
        if self.requested_signal is None:
            self.requested_signal = signum
            LOGGER.info(
                "收到%s，正在请求当前演示正常退出。",
                signal.Signals(signum).name,
            )

        if self.ros_process is not None and self.ros_process.poll() is None:
            try:
                # ros2 launch handles SIGINT by shutting down its launched nodes.
                self.ros_process.send_signal(signal.SIGINT)
            except OSError as error:
                LOGGER.warning("向 ROS launch 转发 SIGINT 失败：%s", error)
        elif (
            self.qwen_process is not None
            and self.qwen_process.poll() is None
        ):
            try:
                self.qwen_process.send_signal(signal.SIGINT)
            except OSError as error:
                LOGGER.warning("向 Qwen 转发 SIGINT 失败：%s", error)

    def raise_if_requested(self) -> None:
        """Stop startup promptly when a signal arrives before ROS launch."""
        if self.requested_signal is not None:
            raise ShutdownRequested(self.requested_signal)


def start_qwen(
    config: DemoConfig, controller: ShutdownController
) -> subprocess.Popen:
    """Start llama-server locally and wait for health and model identity."""
    config.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.log_dir / "llama-server.log"
    command = [
        str(config.llama_bin),
        "-m",
        str(config.llama_model),
        "--host",
        "127.0.0.1",
        "--port",
        str(config.llama_port),
        "--ctx-size",
        "2048",
        "--threads",
        "2",
        "--threads-batch",
        "2",
        "--parallel",
        "1",
        "--cache-ram",
        "0",
        "--no-cache-prompt",
        "--slot-prompt-similarity",
        "0",
        "--no-webui",
        "--jinja",
        "--alias",
        config.llama_model_alias,
    ]

    LOGGER.info("[5/6] 启动 Qwen，等待模型加载完成。")
    LOGGER.info("Qwen 日志：%s", log_path)
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as error:
        raise DemoError("启动 llama-server 失败：{}".format(error))

    LOGGER.info("llama-server 已启动，PID=%s。", process.pid)
    # 立即登记所有权，确保后续异常或超时也会清理该进程。
    controller.qwen_process = process
    health_url = "http://127.0.0.1:{}/health".format(config.llama_port)

    for second in range(1, QWEN_STARTUP_TIMEOUT_SECONDS + 1):
        controller.raise_if_requested()

        if http_is_healthy(health_url, QWEN_HEALTH_TIMEOUT_SECONDS):
            if not llama_model_matches(config):
                raise DemoError(
                    "Qwen 健康检查通过，但服务报告的"
                    "模型标识不匹配。"
                )
            LOGGER.info("Qwen 已在 127.0.0.1:%s 就绪。", config.llama_port)
            return process

        if process.poll() is not None:
            tail = _read_log_tail(log_path)
            raise DemoError(
                "llama-server 提前退出，以下为日志末尾：\n{}".format(tail)
            )

        if second % 15 == 0:
            LOGGER.info("Qwen 仍在加载（已等待约 %s 秒）。", second)
        time.sleep(1)

    tail = _read_log_tail(log_path)
    raise DemoError(
        "等待 {} 秒后，Qwen 仍未通过健康检查；日志末尾：\n{}".format(
            QWEN_STARTUP_TIMEOUT_SECONDS, tail
        )
    )


def print_access_instructions(config: DemoConfig) -> None:
    """Print the Mac-side SSH tunnel command when Tailscale is available."""
    print(
        "网页只监听板端本机地址。请在 Mac 的另一终端运行 "
        "scripts/open-ui.sh 建立 SSH 隧道。"
    )
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None

    board_ip = ""
    if result is not None and result.returncode == 0:
        board_ip = next(
            (line.strip() for line in result.stdout.splitlines() if line.strip()),
            "",
        )

    if board_ip:
        print(
            "  ssh -N -L 18081:127.0.0.1:{} "
            "-o HostKeyAlias=192.168.3.100 orangepi@{}".format(
                config.web_port, board_ip
            )
        )
    else:
        print(
            "  ssh -N -L 18081:127.0.0.1:{} "
            "orangepi@<BOARD_TAILSCALE_IP>".format(config.web_port)
        )
    print(
        "然后在 Mac 打开 http://127.0.0.1:18081/。"
        "按 Ctrl-C 停止本演示。"
    )


def launch_ros(
    config: DemoConfig, controller: ShutdownController
) -> int:
    """Run the ROS launch in the foreground and shut down its process group."""
    controller.raise_if_requested()
    os.environ["ROS_DOMAIN_ID"] = str(config.ros_domain_id)

    command = [
        "ros2",
        "launch",
        "robot_bringup",
        "person_tracking_demo.launch.py",
        "audio_source:={}".format(config.audio_source),
        "input_wav_path:={}".format(config.voice_wav),
        "model_path:={}".format(config.vision_model),
        "run_acceptance_probe:={}".format(
            "true" if config.run_acceptance_probe else "false"
        ),
    ]

    LOGGER.info(
        "[6/6] 启动 ROS 人物跟踪演示："
        "domain=%s，音频=%s，验收探针=%s，"
        "dry_run=true。",
        config.ros_domain_id,
        config.audio_source,
        "true" if config.run_acceptance_probe else "false",
    )
    print_access_instructions(config)

    try:
        process = subprocess.Popen(command, start_new_session=True)
    except OSError as error:
        raise DemoError("启动 ROS 人物跟踪演示失败：{}".format(error))

    controller.ros_process = process
    try:
        return_code = process.wait()
        if return_code != 0:
            LOGGER.error("ROS launch 以状态码 %s 退出。", return_code)
        return return_code
    except OSError as error:
        raise DemoError("等待 ROS launch 结束失败：{}".format(error))
    finally:
        controller.ros_process = None
        stop_owned_process(process, "ROS launch")


def _run(config: DemoConfig, check_only: bool) -> int:
    """Execute preflight and, unless requested otherwise, run the full demo."""
    controller = ShutdownController()
    previous_sigint = signal.getsignal(signal.SIGINT)
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, controller.handle_signal)
    signal.signal(signal.SIGTERM, controller.handle_signal)

    try:
        qwen_ready = preflight(config)
        controller.raise_if_requested()

        if check_only:
            LOGGER.info(
                "只检查模式结束；没有启动 Qwen、ROS 节点或摄像头。"
            )
            report_preflight(config, qwen_ready)
            return 0

        if qwen_ready:
            LOGGER.info("复用已运行的 Qwen 服务。")
        else:
            start_qwen(config, controller)

        controller.raise_if_requested()
        return launch_ros(config, controller)
    except ShutdownRequested as error:
        LOGGER.info("演示已按请求停止。")
        return 128 + error.signum
    except DemoError as error:
        LOGGER.error("错误：%s", error)
        return 1
    except OSError as error:
        LOGGER.error("系统操作失败：%s", error)
        return 1
    except KeyboardInterrupt:
        LOGGER.info("收到 Ctrl-C，正在退出。")
        return 130
    finally:
        stop_owned_process(controller.qwen_process, "Qwen llama-server")
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse options, validate settings, and run the board-side demo."""
    configure_logging()
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config()
    except DemoError as error:
        LOGGER.error("错误：%s", error)
        return 2
    return _run(config, args.check_only)


if __name__ == "__main__":
    sys.exit(main())
