#!/usr/bin/env bash
# 跟踪启动复用项目 Python/ROS 环境，安全参数由 launch 保持。
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/dev.sh" ros launch robot_bringup tracking.launch.py "$@"
