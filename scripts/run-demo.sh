#!/usr/bin/env bash
# 演示进程生命周期由标准 ros2 launch 管理，默认保持 dry-run。
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/dev.sh" ros launch robot_bringup person_tracking_demo.launch.py "$@"
