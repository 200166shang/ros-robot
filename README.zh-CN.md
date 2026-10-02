# ROS Robot

[English](README.md) | [简体中文](README.zh-CN.md)

这是从小沫（XiaoMo）项目迁移而来的 ROS 2 应用，面向 Orange Pi 3B 机器人。
板端工作空间使用 Ubuntu 20.04、ROS 2 Foxy 和 ARM64。

## 软件包

- **接口：** `robot_interfaces`、`monitor_interfaces`
- **相机与感知：** `usb_camera`、`img_decode`、`rknn_yolov6`、`object_track`
- **应用：** `robot_agent`、`robot_voice`、`web_video_server`
- **系统与启动：** `monitor`、`monitor_client`、`robot_bringup`

ROS 软件包统一放在 `ros2_ws/src/`，每个目录对应一个软件包。构建产物放在
`ros2_ws/` 内；仓库根目录用于项目源码、脚本和配置文件。

演示程序依赖本机安装的 Rockchip SDK 头文件、模型权重和语音资源。这些设备
相关文件不纳入 Git。人物跟踪默认使用 `dry_run: true`，不会驱动实体底盘。
