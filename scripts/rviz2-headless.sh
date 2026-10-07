#!/usr/bin/env bash

set -euo pipefail

script_path="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/ros-robot-rviz2-headless"
log_dir="${XDG_CACHE_HOME:-${HOME}/.cache}/ros-robot/rviz2-headless"
pid_file="${runtime_dir}/supervisor.pid"
ready_file="${runtime_dir}/ready"

display="${ROBOT_RVIZ2_DISPLAY:-:99}"
geometry="${ROBOT_RVIZ2_GEOMETRY:-1280x800x24}"
vnc_port="${ROBOT_RVIZ2_VNC_PORT:-5900}"
web_port="${ROBOT_RVIZ2_WEB_PORT:-6080}"
ros_setup="/opt/ros/foxy/setup.zsh"
workspace_setup="${repo_root}/ros2_ws/install/setup.zsh"
rviz_config="${repo_root}/ros2_ws/src/ydlidar/config/ydlidar.rviz"
child_pids=()
child_names=()

usage() {
  cat <<'EOF'
Usage: scripts/rviz2-headless.sh {start|stop|status|logs}

Starts RViz2 in a virtual X display with loopback-only VNC and noVNC endpoints.
Use an SSH tunnel from the Mac to open the noVNC page in a browser.
EOF
}

check_dependencies() {
  local missing=()
  local command_name

  for command_name in Xvfb openbox x11vnc websockify xdpyinfo ss zsh; do
    command -v "${command_name}" >/dev/null 2>&1 || missing+=("${command_name}")
  done

  if [[ ! -d /usr/share/novnc ]]; then
    missing+=("/usr/share/novnc (install the novnc package)")
  fi

  if (( ${#missing[@]} > 0 )); then
    printf 'Missing headless RViz2 dependencies: %s\n' "${missing[*]}" >&2
    printf 'Install them with: sudo apt install xvfb openbox x11vnc novnc websockify x11-utils iproute2 libgl1-mesa-dri\n' >&2
    return 1
  fi

  for required_file in "${ros_setup}" "${workspace_setup}" "${rviz_config}"; do
    if [[ ! -f "${required_file}" ]]; then
      printf 'Required file not found: %s\n' "${required_file}" >&2
      return 1
    fi
  done

  if ! zsh -fc 'source "$1"; source "$2"; command -v rviz2 >/dev/null' \
    _ "${ros_setup}" "${workspace_setup}"; then
    printf 'rviz2 is not available after sourcing the ROS Foxy and workspace setup files.\n' >&2
    printf 'Install it with: sudo apt install ros-foxy-rviz2\n' >&2
    return 1
  fi
}

port_is_listening() {
  local port="$1"

  ss -ltnH | awk -v port=":${port}" '$4 ~ port "$" { found = 1 } END { exit !found }'
}

is_supervisor_running() {
  local pid
  local command_line

  [[ -f "${pid_file}" ]] || return 1
  pid="$(cat "${pid_file}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  [[ -r "/proc/${pid}/cmdline" ]] || return 1
  command_line="$(tr '\0' ' ' < "/proc/${pid}/cmdline")"
  [[ "${command_line}" == *"${script_path} run"* ]]
}

start_child() {
  local name="$1"
  shift

  nohup "$@" >> "${log_dir}/${name}.log" 2>&1 </dev/null &
  child_pids+=("$!")
  child_names+=("${name}")
  printf 'Started %-12s pid %s\n' "${name}" "$!"
}

wait_for_display() {
  local attempts=0

  while (( attempts < 100 )); do
    kill -0 "${child_pids[0]}" 2>/dev/null || {
      printf 'Xvfb exited during startup; see %s/xvfb.log\n' "${log_dir}" >&2
      return 1
    }
    if xdpyinfo -display "${display}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done

  printf 'Timed out waiting for X display %s; see %s/xvfb.log\n' "${display}" "${log_dir}" >&2
  return 1
}

wait_for_port() {
  local port="$1"
  local label="$2"
  local attempts=0

  while (( attempts < 100 )); do
    if port_is_listening "${port}"; then
      return 0
    fi
    sleep 0.1
    attempts=$((attempts + 1))
  done

  printf 'Timed out waiting for %s on loopback port %s\n' "${label}" "${port}" >&2
  return 1
}

run_stack() {
  local index
  local status

  mkdir -p "${runtime_dir}" "${log_dir}"
  rm -f "${ready_file}"
  printf '%s\n' "$$" > "${pid_file}"

  cleanup() {
    local cleanup_index

    trap - EXIT INT TERM
    for (( cleanup_index = ${#child_pids[@]} - 1; cleanup_index >= 0; cleanup_index-- )); do
      kill -TERM "${child_pids[cleanup_index]}" 2>/dev/null || true
    done
    sleep 1
    for (( cleanup_index = ${#child_pids[@]} - 1; cleanup_index >= 0; cleanup_index-- )); do
      kill -KILL "${child_pids[cleanup_index]}" 2>/dev/null || true
    done
    for (( cleanup_index = ${#child_pids[@]} - 1; cleanup_index >= 0; cleanup_index-- )); do
      wait "${child_pids[cleanup_index]}" 2>/dev/null || true
    done
    rm -f "${ready_file}"
    rm -f "${pid_file}"
  }

  trap cleanup EXIT
  trap 'exit 143' INT TERM

  start_child xvfb env DISPLAY="${display}" Xvfb "${display}" \
    -screen 0 "${geometry}" -nolisten tcp -noreset +extension GLX +render
  wait_for_display

  start_child openbox env DISPLAY="${display}" openbox --sm-disable
  start_child x11vnc env DISPLAY="${display}" x11vnc \
    -display "${display}" -forever -shared -localhost -rfbport "${vnc_port}" -nopw -xkb
  wait_for_port "${vnc_port}" x11vnc

  start_child websockify websockify --web /usr/share/novnc \
    "127.0.0.1:${web_port}" "127.0.0.1:${vnc_port}"
  wait_for_port "${web_port}" websockify

  start_child rviz2 env DISPLAY="${display}" LIBGL_ALWAYS_SOFTWARE=1 \
    GALLIUM_DRIVER=llvmpipe QT_X11_NO_MITSHM=1 \
    zsh -fc 'source "$1"; source "$2"; exec rviz2 -d "$3"' \
    _ "${ros_setup}" "${workspace_setup}" "${rviz_config}"

  sleep 1
  for index in "${!child_pids[@]}"; do
    if ! kill -0 "${child_pids[index]}" 2>/dev/null; then
      printf '%s exited during startup; see %s/%s.log\n' \
        "${child_names[index]}" "${log_dir}" "${child_names[index]}" >&2
      return 1
    fi
  done
  : > "${ready_file}"

  printf 'Headless RViz2 ready. SSH tunnel target: 127.0.0.1:%s\n' "${web_port}"
  printf 'Logs: %s\n' "${log_dir}"

  while :; do
    for index in "${!child_pids[@]}"; do
      if ! kill -0 "${child_pids[index]}" 2>/dev/null; then
        status=0
        wait "${child_pids[index]}" || status=$?
        printf '%s exited with status %s; see %s/%s.log\n' \
          "${child_names[index]}" "${status}" "${log_dir}" "${child_names[index]}" >&2
        return 1
      fi
    done
    sleep 1
  done
}

start() {
  local pid
  local attempts=0

  mkdir -p "${runtime_dir}" "${log_dir}"

  if is_supervisor_running; then
    printf 'Headless RViz2 is already running (pid %s).\n' "$(cat "${pid_file}")"
    return 0
  fi
  rm -f "${pid_file}"
  rm -f "${ready_file}"
  check_dependencies

  nohup "${script_path}" run >> "${log_dir}/supervisor.log" 2>&1 </dev/null &
  pid="$!"
  printf '%s\n' "${pid}" > "${pid_file}"

  while (( attempts < 100 )); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      printf 'Headless RViz2 failed to start; inspect %s/supervisor.log\n' "${log_dir}" >&2
      return 1
    fi
    if [[ -f "${ready_file}" ]]; then
      printf 'Headless RViz2 started. Use an SSH tunnel to 127.0.0.1:%s from the Mac.\n' \
        "${web_port}"
      return 0
    fi
    sleep 0.2
    attempts=$((attempts + 1))
  done

  printf 'Headless RViz2 startup is taking longer than expected; inspect %s/supervisor.log\n' \
    "${log_dir}" >&2
  return 1
}

stop() {
  local pid
  local attempts=0

  if ! is_supervisor_running; then
    rm -f "${pid_file}"
    rm -f "${ready_file}"
    printf 'Headless RViz2 is not running.\n'
    return 0
  fi

  pid="$(cat "${pid_file}")"
  kill -TERM "${pid}"
  while (( attempts < 50 )) && kill -0 "${pid}" 2>/dev/null; do
    sleep 0.1
    attempts=$((attempts + 1))
  done
  if kill -0 "${pid}" 2>/dev/null; then
    kill -KILL "${pid}" 2>/dev/null || true
  fi
  rm -f "${pid_file}"
  printf 'Headless RViz2 stopped; the YDLIDAR driver was not stopped.\n'
}

status() {
  if is_supervisor_running; then
    printf 'Headless RViz2 is running (pid %s).\n' "$(cat "${pid_file}")"
    if [[ -f "${ready_file}" ]]; then
      printf 'noVNC loopback port %s is listening.\n' "${web_port}"
    else
      printf 'Headless RViz2 startup is still in progress.\n'
    fi
    return 0
  fi

  rm -f "${pid_file}"
  rm -f "${ready_file}"
  printf 'Headless RViz2 is not running.\n'
  return 1
}

case "${1:-}" in
  start)
    start
    ;;
  stop)
    stop
    ;;
  status)
    status
    ;;
  logs)
    mkdir -p "${log_dir}"
    touch "${log_dir}/supervisor.log"
    exec tail -n 50 -f "${log_dir}"/*.log
    ;;
  run)
    check_dependencies
    run_stack
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
