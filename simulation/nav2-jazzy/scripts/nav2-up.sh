#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

mode="${1:-ideal}"
if [[ "$#" -gt 1 ]]; then
  printf '用法：./scripts/nav2-up.sh [ideal|amcl|slam]\n' >&2
  exit 2
fi

case "$mode" in
  ideal)
    launch_file="nav2_loopback.launch.py"
    ;;
  amcl)
    launch_file="nav2_amcl_loopback.launch.py"
    ;;
  slam)
    launch_file="nav2_slam_loopback.launch.py"
    ;;
  *)
    printf '未知的导航模式：%s（可选 ideal、amcl、slam）\n' "$mode" >&2
    exit 2
    ;;
esac

if ! docker --context colima-ros-nav2 info >/dev/null 2>&1; then
  printf 'Nav2 环境尚未运行。先在 Mac 执行：colima start ros-nav2 --activate=false\n' >&2
  exit 2
fi

if [[ -n "${APT_HTTP_PROXY:-}" ]]; then
  printf '[1/3] 使用配置的 HTTP 代理构建 ROS 2 Jazzy/Nav2 ARM64 镜像……\n'
  APT_HTTP_PROXY="$APT_HTTP_PROXY" NAV2_LAUNCH_FILE="$launch_file" \
    DOCKER_CONTEXT=colima-ros-nav2 docker compose build
else
  printf '[1/3] 使用本地构建缓存检查 ROS 2 Jazzy/Nav2 ARM64 镜像……\n'
  printf '      如果这是首次构建或 Dockerfile 依赖有变化，请设置 APT_HTTP_PROXY。\n'
  NAV2_LAUNCH_FILE="$launch_file" DOCKER_CONTEXT=colima-ros-nav2 docker compose build
fi

printf '[2/3] 启动 Nav2 %s loopback 模式与 HTTP 网关……\n' "$mode"
NAV2_LAUNCH_FILE="$launch_file" DOCKER_CONTEXT=colima-ros-nav2 \
  docker compose up -d --force-recreate
printf '[3/3] 检查网页、地图、初始位姿与 NavigateToPose Action……\n'
for second in {1..120}; do
  if curl --noproxy '*' -fsS --max-time 2 \
    http://127.0.0.1:18091/healthz >/dev/null 2>&1; then
    printf 'Nav2 %s 网页就绪：http://127.0.0.1:18091/\n' "$mode"
    printf '停止服务：./scripts/nav2-down.sh\n'
    exit 0
  fi
  if (( second % 15 == 0 )); then
    printf '  %s 模式已等待 %s 秒……\n' "$mode" "$second"
  fi
  sleep 1
done
printf 'Nav2 尚未就绪。查看日志：DOCKER_CONTEXT=colima-ros-nav2 docker compose logs --tail=120\n' >&2
exit 1
