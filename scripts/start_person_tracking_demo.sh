#!/usr/bin/env bash
set -Eeuo pipefail

SSH_TARGET="${ORANGEPI_SSH_TARGET:-orangepi3b}"
REMOTE_WS="/home/orangepi/code/ros-robot/ros2_ws"
ROS_DOMAIN_ID="${DEMO_ROS_DOMAIN_ID:-74}"
LOCAL_WEB_PORT="${DEMO_LOCAL_WEB_PORT:-18081}"
REMOTE_WEB_PORT="8080"
MODEL_PORT="18080"
AUDIO_SOURCE="${DEMO_AUDIO_SOURCE:-wav_file}"
RUN_ACCEPTANCE_PROBE="${DEMO_RUN_ACCEPTANCE_PROBE:-true}"
WEB_URL="http://127.0.0.1:${LOCAL_WEB_PORT}/"

for value_name in ROS_DOMAIN_ID LOCAL_WEB_PORT; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    printf '错误：%s 必须是数字，当前值为 %q\n' "$value_name" "$value" >&2
    exit 2
  fi
done
case "$AUDIO_SOURCE" in
  wav_file|microphone) ;;
  *) printf 'DEMO_AUDIO_SOURCE 只支持 wav_file 或 microphone。\n' >&2; exit 2 ;;
esac
case "$RUN_ACCEPTANCE_PROBE" in
  true|false) ;;
  *) printf 'DEMO_RUN_ACCEPTANCE_PROBE 只支持 true 或 false。\n' >&2; exit 2 ;;
esac

if ! command -v ssh >/dev/null || ! command -v curl >/dev/null; then
  printf '需要本机已安装 ssh 和 curl。\n' >&2
  exit 2
fi
if ! command -v lsof >/dev/null; then
  printf '需要 lsof 来检查本地端口是否被占用。\n' >&2
  exit 2
fi
if lsof -nP -iTCP:"$LOCAL_WEB_PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  printf '本地端口 %s 已被占用；为避免中断其他服务，本脚本不会关闭它。\n' \
    "$LOCAL_WEB_PORT" >&2
  exit 2
fi
if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$SSH_TARGET" true; then
  printf '无法通过 SSH 连接 %s；请先确认 SSH 别名和机器状态。\n' \
    "$SSH_TARGET" >&2
  exit 2
fi
if ! ssh -o BatchMode=yes "$SSH_TARGET" \
  "ss -ltn | grep -q ':${MODEL_PORT} '"; then
  printf '板端 127.0.0.1:%s 没有模型服务；本脚本不会启动第二个 llama-server。\n' \
    "$MODEL_PORT" >&2
  exit 2
fi
if ssh -o BatchMode=yes "$SSH_TARGET" \
  "ss -ltn | grep -q '127.0.0.1:${REMOTE_WEB_PORT} '"; then
  printf '板端 127.0.0.1:%s 已有网页服务；可能是旧工作区正在占用相机。为避免并发启动，本脚本停止。\n' \
    "$REMOTE_WEB_PORT" >&2
  exit 2
fi

tunnel_pid=""
watcher_pid=""
interrupted=false
cleanup() {
  trap - EXIT INT TERM
  if [[ -n "$watcher_pid" ]] && kill -0 "$watcher_pid" 2>/dev/null; then
    kill "$watcher_pid" 2>/dev/null || true
    wait "$watcher_pid" 2>/dev/null || true
  fi
  if [[ -n "$tunnel_pid" ]] && kill -0 "$tunnel_pid" 2>/dev/null; then
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
  fi
}
on_signal() {
  interrupted=true
}
trap cleanup EXIT
trap on_signal INT TERM

ssh -N -o ExitOnForwardFailure=yes \
  -L "127.0.0.1:${LOCAL_WEB_PORT}:127.0.0.1:${REMOTE_WEB_PORT}" \
  "$SSH_TARGET" &
tunnel_pid=$!
sleep 0.2
if ! kill -0 "$tunnel_pid" 2>/dev/null; then
  wait "$tunnel_pid" || true
  printf 'SSH 隧道启动失败。\n' >&2
  exit 1
fi

wait_for_web() {
  local web_ready=false
  local health_ready=false
  printf '等待隔离 ROS Domain %s 启动回环网页服务……\n' "$ROS_DOMAIN_ID"
  for _ in {1..120}; do
    if ! kill -0 "$tunnel_pid" 2>/dev/null; then
      printf 'SSH 隧道已退出。\n' >&2
      return 1
    fi
    if ssh -q -o BatchMode=yes -o ConnectTimeout=3 "$SSH_TARGET" \
      "ss -ltn | grep -q '127.0.0.1:${REMOTE_WEB_PORT} '"; then
      web_ready=true
      break
    fi
    sleep 1
  done
  if [[ "$web_ready" != true ]]; then
    printf '120 秒内网页服务未就绪。\n' >&2
    return 1
  fi

  for _ in {1..15}; do
    if curl --noproxy '*' -fsS --max-time 1 \
      "http://127.0.0.1:${LOCAL_WEB_PORT}/healthz" >/dev/null 2>&1; then
      health_ready=true
      break
    fi
    sleep 1
  done
  if [[ "$health_ready" != true ]]; then
    printf 'SSH 隧道已建立，但网页健康检查未通过。\n' >&2
    return 1
  fi

  printf '网页已就绪：%s\n' "$WEB_URL"
  if command -v open >/dev/null; then
    open "$WEB_URL" >/dev/null 2>&1 || true
  fi
}

wait_for_web &
watcher_pid=$!
remote_launch="unset COLCON_CURRENT_PREFIX && source /opt/ros/foxy/setup.bash && source ${REMOTE_WS}/install/setup.bash && export ROS_DOMAIN_ID=${ROS_DOMAIN_ID} && exec ros2 launch robot_bringup person_tracking_demo.launch.py audio_source:=${AUDIO_SOURCE} run_acceptance_probe:=${RUN_ACCEPTANCE_PROBE}"
printf '音频来源：%s；验收探针=%s。合成检测框只验证 dry-run 跟踪器。\n' \
  "$AUDIO_SOURCE" "$RUN_ACCEPTANCE_PROBE"
printf '按 Ctrl-C 结束远端演示并关闭本地 SSH 隧道。\n'

if ssh -tt "$SSH_TARGET" \
  "/bin/bash --noprofile --norc -c '${remote_launch}'"; then
  launch_status=0
else
  launch_status=$?
fi
if [[ "$interrupted" == true ]]; then
  exit 0
fi
exit "$launch_status"
