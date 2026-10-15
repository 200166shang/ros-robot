#!/usr/bin/env bash
# 统一项目解释器、ROS 和可选工作区环境，供开发与演示入口复用。
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PYTHON="$PROJECT_ROOT/.venv/bin/python"

project_require_environment() {
  if [[ ! -x "$PROJECT_PYTHON" ]]; then
    printf '项目环境不存在，请先运行 ./scripts/dev.sh sync。\n' >&2
    return 1
  fi
}

project_environment() {
  project_require_environment
  # Foxy 环境脚本会访问未定义变量，仅在加载期间关闭 nounset。
  unset COLCON_CURRENT_PREFIX
  set +u
  source /opt/ros/foxy/setup.bash
  if [[ "${1:-optional}" == workspace ]]; then
    if [[ ! -f "$PROJECT_ROOT/ros2_ws/install/local_setup.bash" ]]; then
      printf '工作区尚未构建，请先运行 ./scripts/dev.sh build。\n' >&2
      return 1
    fi
    source "$PROJECT_ROOT/ros2_ws/install/local_setup.bash"
  elif [[ "${1:-optional}" == optional && -f "$PROJECT_ROOT/ros2_ws/install/local_setup.bash" ]]; then
    source "$PROJECT_ROOT/ros2_ws/install/local_setup.bash"
  fi
  set -u
  export VIRTUAL_ENV="$PROJECT_ROOT/.venv"
  export PATH="$VIRTUAL_ENV/bin:$PATH"
  export PYTHONNOUSERSITE=1
}
