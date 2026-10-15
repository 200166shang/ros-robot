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

固定跟踪组合的首次准备、启动、控制与故障排查见
[跟踪操作指南](ros2_ws/src/robot_bringup/README.md)。

## 构建与测试

项目使用板端系统 Python 3.8 创建的根目录 uv 环境。按
[环境指南](docs/development-environment.md) 安装 uv 0.8.22、确认系统基线后运行：

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

只有 `sync` 安装锁定依赖；普通命令复用 `.venv`，不会同步依赖或修改锁文件。
`python`、`ros` 分别执行项目 Python 和 ROS 命令。ROS 源码包仍由 colcon
构建安装；现有 `colcon.sh` 与演示脚本复用相同环境。语音工具也安装在此环境，
模型保留在仓库外；`verify` 不启动节点或实际设备。

各软件包特有的后端、SDK、资源和测试准备步骤见对应的软件包 README。

演示程序依赖本机安装的 Rockchip SDK 头文件、模型权重和语音资源。这些设备
相关文件不纳入 Git。人物跟踪默认使用 `dry_run: true`，不会驱动实体底盘。


本地 LLM 桥接已弃用，robot_agent 仅提供 Online Agent。启动及外部配置见 [在线文本说明](docs/online-agent-text.md)，相机、融合及 Follow 见 [感知控制](docs/online-agent-perception.md)。run-demo.sh 使用标准 ROS launch 启动跟踪与网页；网页设备控制独立于模型推理。

完整在线语音、文本、感知和记忆的一次启动与验收见 [统一 Online Agent 指南](docs/online-agent.md)。
