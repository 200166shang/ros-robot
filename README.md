# ROS Robot

[English](README.md) | [简体中文](README.zh-CN.md)

ROS 2 application software for the Orange Pi 3B robot, migrated from the XiaoMo
project. The board workspace targets Ubuntu 20.04, ROS 2 Foxy, and ARM64.

## Packages

- **Interfaces:** `robot_interfaces`, `monitor_interfaces`
- **Camera and perception:** `usb_camera`, `img_decode`, `rknn_yolov6`, `object_track`
- **Radar:** [`ydlidar`](ros2_ws/src/ydlidar/README.md)
- **Application:** `robot_agent`, `robot_voice`, `web_video_server`
- **System and launch:** `monitor`, `monitor_client`, `robot_bringup`

ROS packages are organized under `ros2_ws/src/`, one package per directory.
Build output belongs under `ros2_ws/`; the repository root is for source,
scripts, and project files.

For fixed tracking setup, startup, controls, and troubleshooting, see the
[tracking operator guide](ros2_ws/src/robot_bringup/README.md).

## Build and test

Use the root uv environment on the board's system Python 3.8. Install
[uv 0.8.22 and the system baseline](docs/development-environment.md), then run:

```bash
export PATH="$HOME/.local/bin:$PATH"
./scripts/dev.sh sync
./scripts/dev.sh build --executor sequential --cmake-args \
  -DRKNN_API_INCLUDE_DIR=/home/orangepi/sdk/rknn/include
./scripts/dev.sh lint
./scripts/dev.sh test -q tests ros2_ws/src
./scripts/dev.sh test-ros --executor sequential
./scripts/dev.sh test-result --verbose
./scripts/dev.sh verify
```

Only `sync` installs locked dependencies. Other commands use the existing
`.venv`; `python` and `ros` run project Python and ROS commands. Colcon still
owns all ROS source package installations. The existing `colcon.sh` and demo
scripts delegate to the same environment. See the [environment guide](docs/development-environment.md)
for dependency updates, speech artifact hashes, and checks that require no hardware.

Package-specific backend, SDK, asset, and test setup is documented in each
package README.

The demo depends on locally installed Rockchip SDK headers, perception model weights, and
optional local voice assets. These machine-specific files are kept outside Git. The tracking
demo defaults to `dry_run: true` and does not drive a physical base.


The local LLM bridge is retired. `robot_agent` provides Online Agent only;
see [online text startup](docs/online-agent-text.md). `run-demo.sh` starts the
tracking/web composition and accepts `with_online_agent:=true` plus an external
`online_config_file`. Web device controls are independent of model inference.

For unified online text, WAV, perception and memory startup, see the [Online Agent guide](docs/online-agent.md).
