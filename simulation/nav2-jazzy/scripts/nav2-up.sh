#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if ! docker --context colima-ros-nav2 info >/dev/null 2>&1; then
  printf 'Nav2 环境尚未运行。先在 Mac 执行：colima start ros-nav2 --activate=false\n' >&2
  exit 2
fi

if ! printenv APT_HTTP_PROXY >/dev/null 2>&1; then
  printf '首次构建需让容器访问 ROS apt 源。请按本机代理设置 APT_HTTP_PROXY 后重试。\n' >&2
  printf '示例：APT_HTTP_PROXY=http://192.168.5.2:7890 ./scripts/nav2-up.sh\n' >&2
  exit 2
fi

printf '[1/3] 正在构建 ROS 2 Jazzy/Nav2 ARM64 镜像……\n'
APT_HTTP_PROXY="$(printenv APT_HTTP_PROXY)" DOCKER_CONTEXT=colima-ros-nav2 docker compose build
printf '[2/3] 正在启动 Nav2 loopback 与 HTTP 网关……\n'
DOCKER_CONTEXT=colima-ros-nav2 docker compose up -d
printf '[3/3] 检查网页与 Nav2 Action 就绪状态……\n'
for second in {1..60}; do
  if curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:18091/healthz >/dev/null; then
    printf 'Nav2 网页就绪：http://127.0.0.1:18091/\n'
    printf '停止服务：./scripts/nav2-down.sh\n'
    exit 0
  fi
  if (( second % 10 == 0 )); then
    printf '  已等待 %s 秒……\n' "$second"
  fi
  sleep 1
done
printf 'Nav2 尚未就绪。查看日志：DOCKER_CONTEXT=colima-ros-nav2 docker compose logs --tail=120\n' >&2
exit 1
