#!/usr/bin/env bash
# 隧道脚本也使用严格模式，避免空配置造成错误端口或 SSH 目标。
set -Eeuo pipefail

# 本脚本运行在 Mac：本地端口映射到板端 loopback 的 Web 端口。
SSH_TARGET="${ORANGEPI_SSH_TARGET:-orangepi-ts}"
SSH_HOST_KEY_ALIAS="${ORANGEPI_HOST_KEY_ALIAS:-192.168.3.100}"
LOCAL_WEB_PORT="${DEMO_LOCAL_WEB_PORT:-18081}"
REMOTE_WEB_PORT="${DEMO_WEB_PORT:-8080}"
WEB_URL="http://127.0.0.1:${LOCAL_WEB_PORT}/"
OPEN_BROWSER="${DEMO_OPEN_BROWSER:-true}"

usage() {
  cat <<'USAGE'
用法：scripts/open-ui.sh [--help]

在 Orange Pi 演示启动后于 Mac 运行。本脚本只建立 ROS 网页界面的 SSH 隧道，
不会启动或停止 Qwen、ROS。

可选环境变量：
  ORANGEPI_SSH_TARGET（默认 orangepi-ts；SSH 配置别名或 user@host）
  ORANGEPI_HOST_KEY_ALIAS（默认 192.168.3.100）
  DEMO_LOCAL_WEB_PORT（默认 18081）
  DEMO_WEB_PORT（默认 8080）
  DEMO_OPEN_BROWSER=true|false（默认 true）
USAGE
}

# 参数/依赖错误统一提示并退出；脚本只负责 Mac 的网络隧道和浏览器。
die() {
  printf '错误：%s\n' "$*" >&2
  exit 1
}

log_step() {
  printf '\n[%s] %s\n' "$1" "$2"
}

log_ok() {
  printf '  完成：%s\n' "$1"
}

# 只接受零个参数或一个帮助参数，避免静默忽略多余输入。
if [[ "$#" -gt 1 ]]; then
  printf '错误：一次只能指定一个选项。\n' >&2
  usage >&2
  exit 2
fi

if [[ "$#" -eq 1 ]]; then
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf '错误：不支持的选项：%s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
fi

validate_settings() {
  local local_port_number
  local remote_port_number

  if [[ ! "$LOCAL_WEB_PORT" =~ ^[0-9]+$ ]]; then
    die "本机网页端口必须是数字，当前值：$LOCAL_WEB_PORT"
  fi

  if [[ ! "$REMOTE_WEB_PORT" =~ ^[0-9]+$ ]]; then
    die "板端网页端口必须是数字，当前值：$REMOTE_WEB_PORT"
  fi

  if [[ "${#LOCAL_WEB_PORT}" -gt 5 ]]; then
    die "本机网页端口必须在 1–65535 范围内，当前值：$LOCAL_WEB_PORT"
  fi

  if [[ "${#REMOTE_WEB_PORT}" -gt 5 ]]; then
    die "板端网页端口必须在 1–65535 范围内，当前值：$REMOTE_WEB_PORT"
  fi

  # 按十进制解释，避免 08081 这样的写法被 Bash 当成八进制。
  local_port_number=$((10#$LOCAL_WEB_PORT))
  remote_port_number=$((10#$REMOTE_WEB_PORT))

  if (( local_port_number < 1 || local_port_number > 65535 )); then
    die "本机网页端口范围必须是 1–65535，当前值：$LOCAL_WEB_PORT"
  fi

  if (( remote_port_number < 1 || remote_port_number > 65535 )); then
    die "板端网页端口范围必须是 1–65535，当前值：$REMOTE_WEB_PORT"
  fi

  if [[ "$OPEN_BROWSER" != true && "$OPEN_BROWSER" != false ]]; then
    die "DEMO_OPEN_BROWSER 只能是 true 或 false，当前值：$OPEN_BROWSER"
  fi
}

validate_settings

if ! command -v ssh >/dev/null 2>&1; then
  die '缺少必要命令：ssh。'
fi

if ! command -v curl >/dev/null 2>&1; then
  die '缺少必要命令：curl。'
fi

if ! command -v lsof >/dev/null 2>&1; then
  die '缺少必要命令：lsof。'
fi

SSH_OPTIONS=(
  -o BatchMode=yes
  -o ConnectTimeout=8
  -o "HostKeyAlias=${SSH_HOST_KEY_ALIAS}"
)
# healthz 用来确认端口上确实是本项目网页，而不是任意其他进程。
LOCAL_HEALTH="http://127.0.0.1:${LOCAL_WEB_PORT}/healthz"
REMOTE_HEALTH="http://127.0.0.1:${REMOTE_WEB_PORT}/healthz"

open_browser() {
  # 只有 macOS 存在 open 命令时才自动开浏览器；关闭此选项不影响隧道。
  if [[ "$OPEN_BROWSER" == true ]] && command -v open >/dev/null 2>&1; then
    open "$WEB_URL" >/dev/null 2>&1 || true
  fi
}

if lsof -nP -iTCP:"$LOCAL_WEB_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  # 只有健康检查确认是可用隧道时才复用；其他占用者不触碰。
  if curl --noproxy '*' -fsS --max-time 2 "$LOCAL_HEALTH" >/dev/null; then
    log_ok "本机端口 ${LOCAL_WEB_PORT} 已有可用网页隧道"
    printf '复用已有隧道，网页地址：%s\n' "$WEB_URL"
    open_browser
    exit 0
  fi
  die "本机端口 $LOCAL_WEB_PORT 已被占用，但不是可用的演示隧道。" \
    '未停止任何进程。'
fi

log_step '1/4' "通过 SSH 检查板端网页服务（端口 ${REMOTE_WEB_PORT}）"
if ! ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" \
  "curl --noproxy '*' -fsS --max-time 3 '${REMOTE_HEALTH}' >/dev/null"; then
  die "无法访问板端网页健康检查接口。请先启动板端演示，" \
    "并检查 SSH 目标 '$SSH_TARGET'。"
fi
log_ok '板端网页服务健康'

TUNNEL_PID=""
cleanup() {
  # 此脚本只拥有 Mac 上的 SSH 隧道，不会停止板端 ROS 或 Qwen。
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$TUNNEL_PID" ]] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 只绑定本机 loopback，避免把无认证页面暴露给其他设备。
# 端口绑定失败时，ExitOnForwardFailure 会让 SSH 立即退出。
log_step '2/4' \
  "建立网页隧道：本机端口 ${LOCAL_WEB_PORT} → 板端端口 ${REMOTE_WEB_PORT}"
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  "${SSH_OPTIONS[@]}" \
  -L "127.0.0.1:${LOCAL_WEB_PORT}:127.0.0.1:${REMOTE_WEB_PORT}" \
  "$SSH_TARGET" &
TUNNEL_PID=$!

TUNNEL_READY=false
# SSH 进程启动不代表网页已可访问；通过本地 healthz 检查整条链路。
log_step '3/4' '验证网页是否能通过隧道访问'
for second in {1..15}; do
  if curl --noproxy '*' -fsS --max-time 1 "$LOCAL_HEALTH" >/dev/null 2>&1; then
    TUNNEL_READY=true
    break
  fi
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    wait "$TUNNEL_PID" || true
    die 'SSH 隧道在网页健康检查通过前退出。'
  fi
  if (( second % 5 == 0 )); then
    printf '  隧道已建立，正在等待网页响应（已等待 %s 秒）……\n' "$second"
  fi
  sleep 1
done
if [[ "$TUNNEL_READY" != true ]]; then
  die 'SSH 隧道已启动，但转发后的网页健康检查失败。'
fi

log_step '4/4' '网页已就绪'
printf 'ROS 网页界面：%s\n' "$WEB_URL"
printf '请保持此终端运行；按 Ctrl-C 只会关闭 SSH 隧道。\n'
open_browser
# wait 保持前台运行并转发退出状态；Ctrl-C 触发上面的 trap 清理隧道进程。
wait "$TUNNEL_PID"
