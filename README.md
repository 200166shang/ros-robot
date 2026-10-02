# ROS Robot

[English](README.md) | [简体中文](README.zh-CN.md)

ROS 2 application software for the Orange Pi 3B robot, migrated from the XiaoMo
project. The board workspace targets Ubuntu 20.04, ROS 2 Foxy, and ARM64.

## Packages

- **Interfaces:** `robot_interfaces`, `monitor_interfaces`
- **Camera and perception:** `usb_camera`, `img_decode`, `rknn_yolov6`, `object_track`
- **Application:** `robot_agent`, `robot_voice`, `web_video_server`
- **System and launch:** `monitor`, `monitor_client`, `robot_bringup`

ROS packages are organized under `ros2_ws/src/`, one package per directory.
Build output belongs under `ros2_ws/`; the repository root is for source,
scripts, and project files.

The demo depends on locally installed Rockchip SDK headers, model weights, and
voice assets. These machine-specific files are kept outside Git. The tracking
demo defaults to `dry_run: true` and does not drive a physical base.
