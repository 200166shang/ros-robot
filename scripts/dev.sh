#!/usr/bin/env bash
# 同步是唯一安装入口；普通命令不更改依赖或锁文件。
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/project-env.sh"
command_name="${1:---help}"
if [[ $# -gt 0 ]]; then shift; fi

case "$command_name" in
  sync)
    cd "$PROJECT_ROOT"
    if ! command -v uv >/dev/null 2>&1; then
      printf '需要 uv 0.8.22，请按 README 安装后运行 ./scripts/dev.sh sync。\n' >&2
      exit 1
    fi
    if [[ ! -x "$PROJECT_PYTHON" ]]; then
      uv venv --python /usr/bin/python3 --no-python-downloads --system-site-packages .venv
    fi
    export UV_PROJECT_ENVIRONMENT="$PROJECT_ROOT/.venv"
    export VIRTUAL_ENV="$PROJECT_ROOT/.venv"
    exec uv sync --locked --python /usr/bin/python3 --no-python-downloads "$@"
    ;;
  lint|format)
    project_require_environment
    cd "$PROJECT_ROOT"
    if [[ $# == 0 ]]; then set -- .; fi
    if [[ "$command_name" == format ]]; then
      exec "$PROJECT_PYTHON" -m ruff format "$@"
    fi
    "$PROJECT_PYTHON" -m ruff format --check "$@"
    exec "$PROJECT_PYTHON" -m ruff check "$@"
    ;;
  build)
    project_environment base
    source "$SCRIPT_DIR/ydlidar-sdk-env.zsh"
    cd "$PROJECT_ROOT/ros2_ws"
    # 合并调用者的 CMake 选项，避免覆盖后丢失后端/SDK 参数。
    build_arguments=()
    has_cmake_arguments=false
    for argument in "$@"; do
      build_arguments+=("$argument")
      if [[ "$argument" == --cmake-args ]]; then
        has_cmake_arguments=true
        build_arguments+=("-DPYTHON_EXECUTABLE=$PROJECT_PYTHON" "-DPython3_EXECUTABLE=$PROJECT_PYTHON")
      fi
    done
    if [[ "$has_cmake_arguments" == false ]]; then
      build_arguments+=(--cmake-args "-DPYTHON_EXECUTABLE=$PROJECT_PYTHON" "-DPython3_EXECUTABLE=$PROJECT_PYTHON")
    fi
    exec "$PROJECT_PYTHON" -m colcon build --symlink-install "${build_arguments[@]}"
    ;;
  test)
    export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-174}"
    export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
    project_environment workspace
    cd "$PROJECT_ROOT"
    if [[ $# == 0 ]]; then set -- tests ros2_ws/src; fi
    exec "$PROJECT_PYTHON" -m pytest "$@"
    ;;
  test-ros|test-result)
    export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-174}"
    export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
    project_environment workspace
    cd "$PROJECT_ROOT/ros2_ws"
    if [[ "$command_name" == test-ros ]]; then
      exec "$PROJECT_PYTHON" -m colcon test --python-testing pytest --return-code-on-test-failure "$@"
    fi
    exec "$PROJECT_PYTHON" -m colcon test-result "$@"
    ;;
  ros)
    project_environment workspace
    source "$SCRIPT_DIR/ydlidar-sdk-env.zsh"
    exec "$PROJECT_PYTHON" /opt/ros/foxy/bin/ros2 "$@"
    ;;
  colcon)
    case "${1:-}" in
      build|test|test-result)
        colcon_command="$1"
        shift
        if [[ "$colcon_command" == test ]]; then colcon_command=test-ros; fi
        exec "$SCRIPT_DIR/dev.sh" "$colcon_command" "$@"
        ;;
    esac
    project_environment base
    cd "$PROJECT_ROOT/ros2_ws"
    exec "$PROJECT_PYTHON" -m colcon "$@"
    ;;
  verify)
    project_environment workspace
    exec "$PROJECT_PYTHON" "$SCRIPT_DIR/verify_environment.py" "$@"
    ;;
  python)
    project_environment
    exec "$PROJECT_PYTHON" "$@"
    ;;
  --help|-h)
    printf '用法：./scripts/dev.sh <命令> [参数]\n命令：sync format lint test build test-ros test-result ros python colcon verify\n'
    ;;
  *)
    printf '未知项目命令：%s（使用 --help 查看用法）。\n' "$command_name" >&2
    exit 2
    ;;
esac
