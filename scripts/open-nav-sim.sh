#!/usr/bin/env bash
# Run on the Mac: expose the board's chat UI and give the board a private
# reverse tunnel to the Mac-hosted Nav2 simulation. Nothing is started/stopped
# on the Orange Pi by this script.
set -Eeuo pipefail

SSH_TARGET="${ORANGEPI_SSH_TARGET:-orangepi-ts}"
SSH_HOST_KEY_ALIAS="${ORANGEPI_HOST_KEY_ALIAS:-192.168.3.100}"
LOCAL_CHAT_PORT="${DEMO_LOCAL_WEB_PORT:-18081}"
BOARD_CHAT_PORT="${DEMO_WEB_PORT:-8080}"
LOCAL_NAV2_PORT="${NAV2_LOCAL_WEB_PORT:-18091}"
BOARD_NAV2_TUNNEL_PORT="${NAV2_BOARD_TUNNEL_PORT:-18092}"

usage() {
  cat <<'USAGE'
用法：scripts/open-nav-sim.sh [--help]

在 Mac 运行。建立同一条 SSH 会话：
  Mac 18081 → Orange Pi 8080（聊天控制台）
  Orange Pi 127.0.0.1:18092 → Mac 127.0.0.1:18091（Nav2 API）

前置条件：Mac 已启动 Nav2 网页/网关；Orange Pi 已联网且 SSH 可登录。
隧道可以先于板端演示启动；之后再在板端运行 run-demo.sh --navigation-sim。
Ctrl-C 只会关闭本脚本创建的 SSH 隧道，不会停止两端服务。

可选环境变量：ORANGEPI_SSH_TARGET、ORANGEPI_HOST_KEY_ALIAS、
DEMO_LOCAL_WEB_PORT、DEMO_WEB_PORT、NAV2_LOCAL_WEB_PORT、
NAV2_BOARD_TUNNEL_PORT。
USAGE
}

die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

if [[ "$#" -gt 1 ]]; then
  usage >&2
  exit 2
fi
if [[ "$#" -eq 1 ]]; then
  case "$1" in
    --help|-h) usage; exit 0 ;;
    *) die "不支持的选项：$1" ;;
  esac
fi

for tool in ssh curl lsof; do
  command -v "$tool" >/dev/null 2>&1 || die "找不到必要命令：$tool"
done

CHAT_URL="http://127.0.0.1:${LOCAL_CHAT_PORT}/"
NAV2_URL="http://127.0.0.1:${LOCAL_NAV2_PORT}/"
NAV2_HEALTH_URL="http://127.0.0.1:${LOCAL_NAV2_PORT}/healthz"
SSH_OPTIONS=(
  -o BatchMode=yes
  -o ConnectTimeout=8
  -o "HostKeyAlias=${SSH_HOST_KEY_ALIAS}"
  -o ServerAliveInterval=30
  -o ServerAliveCountMax=3
)

if lsof -nP -iTCP:"$LOCAL_CHAT_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  die "Mac 本地端口 ${LOCAL_CHAT_PORT} 已被占用；未停止任何进程。"
fi
if ! curl --noproxy '*' -fsS --max-time 3 "$NAV2_HEALTH_URL" >/dev/null; then
  die "Mac Nav2 网关未就绪。先启动 simulation/nav2-jazzy/scripts/nav2-up.sh。"
fi
TUNNEL_PID=""
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  if [[ -n "$TUNNEL_PID" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '[1/3] 建立双向 SSH 隧道……\n'
ssh -N -o ExitOnForwardFailure=yes "${SSH_OPTIONS[@]}" \
  -L "127.0.0.1:${LOCAL_CHAT_PORT}:127.0.0.1:${BOARD_CHAT_PORT}" \
  -R "127.0.0.1:${BOARD_NAV2_TUNNEL_PORT}:127.0.0.1:${LOCAL_NAV2_PORT}" \
  "$SSH_TARGET" &
TUNNEL_PID=$!

printf '[2/3] 验证网页和板端反向接口……\n'
ready=false
for attempt in {1..15}; do
  if ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" \
    "curl --noproxy '*' -fsS --max-time 2 'http://127.0.0.1:${BOARD_NAV2_TUNNEL_PORT}/healthz' >/dev/null"; then
    ready=true
    break
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    wait "$TUNNEL_PID" || true
    die 'SSH 隧道提前退出；请检查两个方向的端口转发是否允许。'
  fi
  sleep 1
done
[[ "$ready" == true ]] || die '双向隧道健康检查超时。'

printf '[3/3] SSH 双向隧道已就绪。\n聊天控制台：%s\nNav2 地图：%s\n' \
  "$CHAT_URL" "$NAV2_URL"
CHAT_READY=false
if curl --noproxy '*' -fsS --max-time 1 \
  "http://127.0.0.1:${LOCAL_CHAT_PORT}/healthz" >/dev/null 2>&1; then
  CHAT_READY=true
else
  printf '板端聊天网页尚未启动；在板端运行 run-demo.sh --navigation-sim 后再打开聊天地址。\n'
fi
if command -v open >/dev/null 2>&1; then
  open "$NAV2_URL" >/dev/null 2>&1 || true
  if [[ "$CHAT_READY" == true ]]; then
    open "$CHAT_URL" >/dev/null 2>&1 || true
  fi
fi
printf '保持此终端运行；按 Ctrl-C 只关闭本 SSH 隧道。\n'
wait "$TUNNEL_PID"
