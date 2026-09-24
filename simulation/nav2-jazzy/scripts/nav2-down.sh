#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

printf '[1/2] 停止本项目 Nav2 服务……\n'
DOCKER_CONTEXT=colima-ros-nav2 docker compose down
printf '[2/2] 服务已停止；需要释放 Linux 虚拟机内存时再执行：colima stop ros-nav2\n'
