# ROS Robot

[English](README.md) | [简体中文](README.zh-CN.md)

这是从小沫（XiaoMo）项目迁移而来的 ROS 2 应用，面向 Orange Pi 3B 机器人。
板端工作空间使用 Ubuntu 20.04、ROS 2 Foxy 和 ARM64。

## 软件包

- **接口：** `robot_interfaces`、`monitor_interfaces`
- **相机与感知：** `usb_camera`、`img_decode`、`rknn_yolov6`、`object_track`
- **雷达：** [`ydlidar` 可视化说明](ros2_ws/src/ydlidar/README.md)
- **应用：** `robot_agent`、`robot_voice`、`web_video_server`
- **系统与启动：** `monitor`、`monitor_client`、`robot_bringup`

ROS 软件包统一放在 `ros2_ws/src/`，每个目录对应一个软件包。构建产物放在
`ros2_ws/` 内；仓库根目录用于项目源码、脚本和配置文件。

## 构建与测试

先加载 ROS 2 Foxy 环境，然后在仓库根目录运行工作区命令。包装脚本会切换到
`ros2_ws/` 再调用 `colcon`，并原样传递参数：

```bash
source /opt/ros/foxy/setup.bash
./scripts/colcon.sh build --symlink-install
./scripts/colcon.sh test
./scripts/colcon.sh test-result --verbose
```

各软件包特有的后端、SDK、资源和测试准备步骤见对应的软件包 README。

演示程序依赖本机安装的 Rockchip SDK 头文件、模型权重和语音资源。这些设备
相关文件不纳入 Git。人物跟踪默认使用 `dry_run: true`，不会驱动实体底盘。
