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

Source the ROS 2 Foxy environment, then run the workspace commands from the
repository root. The wrapper runs `colcon` from `ros2_ws/` and forwards its
arguments:

```bash
source /opt/ros/foxy/setup.bash
./scripts/colcon.sh build --symlink-install
./scripts/colcon.sh test
./scripts/colcon.sh test-result --verbose
```

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
