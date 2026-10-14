#!/usr/bin/env bash
# 加载 ROS 运行环境，演示进程生命周期由标准 ros2 launch 管理。
if ! command -v shopt >/dev/null 2>&1; then
  printf '错误：此入口需要 Bash。请运行 ./scripts/run-demo.sh（不要用 sh）。\n' >&2
  exit 2
fi

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
FOXY_SETUP="/opt/ros/foxy/setup.bash"
WORKSPACE_SETUP="${PROJECT_ROOT}/ros2_ws/install/setup.bash"

if [[ ! -f "${FOXY_SETUP}" ]]; then
  printf '错误：找不到 ROS 2 Foxy 环境文件：%s\n' "${FOXY_SETUP}" >&2
  exit 1
fi

if [[ ! -f "${WORKSPACE_SETUP}" ]]; then
  printf '错误：找不到已构建的 ROS 工作区环境文件：%s\n' \
    "${WORKSPACE_SETUP}" >&2
  printf '请先按照项目文档构建 ros2_ws。\n' >&2
  exit 1
fi

# Foxy setup 可能读取未定义变量，因此仅加载期间关闭 nounset。
unset COLCON_CURRENT_PREFIX
set +u
if ! source "${FOXY_SETUP}"; then
  printf '错误：加载 ROS 2 Foxy 环境失败。\n' >&2
  exit 1
fi

if ! source "${WORKSPACE_SETUP}"; then
  printf '错误：加载项目 ROS 工作区环境失败。\n' >&2
  exit 1
fi
set -u

# 加载持久 SDK 后进入网页与跟踪演示，不再启动本地模型。
source "${SCRIPT_DIR}/ydlidar-sdk-env.zsh"
exec ros2 launch robot_bringup person_tracking_demo.launch.py "$@"
