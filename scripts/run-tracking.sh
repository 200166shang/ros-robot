#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

unset COLCON_CURRENT_PREFIX
source /opt/ros/foxy/setup.bash
source "${PROJECT_ROOT}/ros2_ws/install/setup.bash"
source "${SCRIPT_DIR}/ydlidar-sdk-env.zsh"

exec ros2 launch robot_bringup tracking.launch.py "$@"
