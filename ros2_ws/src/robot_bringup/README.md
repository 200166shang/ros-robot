# Fixed tracking operator guide

本文介绍固定跟踪组合的安装、启动、调试和安全操作。日常入口使用
`tracking.launch.py`；LiDAR Fusion 和 Follow 在运行时分别通过 Service 控制。

## 中文操作指南

### 首次安装与构建

先按 [detector 准备说明](../rknn_yolov6/README.md) 安装匹配的 RKNN runtime、Rockchip MPP/RGA 开发库，并把官方 `rknn_api.h` 放在仓库外。当前板子的头文件目录为 `$HOME/sdk/rknn/include`。随后准备持久 YDLIDAR SDK 并构建硬件组合：

```bash
cd ~/code/ros-robot
./scripts/install-ydlidar-sdk.sh
source /opt/ros/foxy/setup.bash
source scripts/ydlidar-sdk-env.zsh
./scripts/colcon.sh build --symlink-install --packages-up-to robot_bringup \
  --parallel-workers 1 --cmake-args -DBUILD_TESTING=OFF \
  -DRKNN_API_INCLUDE_DIR="$HOME/sdk/rknn/include"
source ros2_ws/install/setup.bash
```

此命令逐包构建硬件运行目标，减少 Orange Pi 上的编译内存压力；开发测试仍按各 package 的测试说明运行。`RKNN_API_INCLUDE_DIR` 按实际外部头文件位置调整。

安装器将固定版本的 SDK 放在 `$HOME/.local/opt/ydlidar-sdk/1.2.7`，源码和构建目录使用仓库外的临时目录。若要使用其他持久前缀，在安装前设置 `YDLIDAR_SDK_PREFIX`；不要把 SDK 或生成的构建文件放进 Git 源码。

每个新 Shell 都要加载 ROS、SDK 和工作区环境。Zsh 用户将 Foxy 与工作区的 `setup.bash` 换成 `setup.zsh`；`ydlidar-sdk-env.zsh` 可由 Bash 和 Zsh 加载。`scripts/run-tracking.sh` 会为当前 checkout 加载这些环境。

### 启动固定组合

当前 Orange Pi Foxy 环境没有 `foxglove_bridge` 包，因此从仓库根目录先排除可选 Bridge 启动：

```bash
./scripts/run-tracking.sh with_foxglove:=false
```

该薄包装加载 Foxy、本 checkout 的 `ros2_ws/install` 和持久 SDK 环境，然后直接交给 `ros2 launch robot_bringup tracking.launch.py`。它将命令行参数原样传给同一 Launch。

也可在已加载环境的终端直接启动：

```bash
cd ~/code/ros-robot
source /opt/ros/foxy/setup.bash
source scripts/ydlidar-sdk-env.zsh
source ros2_ws/install/setup.bash
ros2 launch robot_bringup tracking.launch.py with_foxglove:=false
```

唯一的 Launch 参数是 `with_foxglove`，默认 `true`。安装了兼容当前 ROS 版本的 Foxglove Bridge 后，可省略参数或明确开启：

```bash
./scripts/run-tracking.sh with_foxglove:=true
# 或直接运行：
ros2 launch robot_bringup tracking.launch.py with_foxglove:=true
```

固定组合只包含日常相机、检测、雷达、平台 TF 与跟踪链路；Agent、Voice 和 Web 视频演示由另一个入口负责。不要传入 `mode` 或逐模块开关，这些不是该 Launch 支持的参数。

### 使用已有 ROSBridge 观看

当前板子已安装 `rosbridge_server`。在另一个已加载 ROS 环境的终端启动观察桥接：

```bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

网页或 Foxglove 选择 ROSBridge 连接，地址为 `ws://<板子 IP>:9090`，观看 `/camera/image_det_track` 和 `/scan`。组合仍使用 `with_foxglove:=false`，避免重复启动 Bridge；ROSBridge 由自己的终端管理，不属于固定组合的六个进程。

### 启用融合与 Follow

启动时 LiDAR Fusion 关闭、Follow 处于 standby。先确认扫描、相机检测输入和平台 TF 正常：

```bash
ros2 topic hz /scan
ros2 topic hz /camera/image_det
ros2 topic hz /ai_msg_det
ros2 run tf2_ros tf2_echo camera laser_link
```

然后先启用 LiDAR Fusion，服务确认成功后再启用 Follow：

```bash
ros2 service call /tracking/set_lidar_enabled std_srvs/srv/SetBool "{data: true}"
ros2 service call /tracking/set_enabled std_srvs/srv/SetBool "{data: true}"
```

若服务返回 `success: false`，按返回的原因检查依赖后重试。Follow 需要同步的图像与检测、可用的 `camera <- laser_link` TF、已开启的融合以及新鲜 `/scan`。启动顺序不会由节点自动补齐。

停止时先关闭 Follow，再关闭融合：

```bash
ros2 service call /tracking/set_enabled std_srvs/srv/SetBool "{data: false}"
ros2 service call /tracking/set_lidar_enabled std_srvs/srv/SetBool "{data: false}"
```

关闭融合会清除跟踪器的扫描与距离状态；若 Follow 仍开启，跟踪器会将其返回 standby 并发出零命令。此操作不会停止或接管 YDLIDAR 驱动。

### 安全与进程生命周期

`object_track/config/object_track.yaml` 默认 `dry_run: true`。在此设置下，跟踪器只记录速度预览，不创建或发布 `/tracking/cmd_vel_safe` 的 `Twist` 消息。日常启动和验收保持此设置。

ROS Launch 按普通生命周期管理本次启动的进程。按 Ctrl-C 会关闭该 Launch 启动的进程；节点退出后不会自动重启，也不会关闭其他终端或外部启动的 ROS 进程。故障恢复由操作者检查原因并重新启动相应进程。

Foxglove 是观察端；断开浏览器连接不是停止 Launch 的操作。板端验收时应断开再连接 Foxglove，并确认 `/scan` 仍在更新，再记录实际结果。本次板端记录及已验证、跳过的项目见 [验收报告](../../../docs/reports/tracking-orange-pi-2026-10-13.md)。

### 故障排查

| 现象 | 检查与处理 |
|---|---|
| 构建提示找不到 `ydlidar_sdk` / `ydlidar_sdkConfig.cmake` | 运行 `./scripts/install-ydlidar-sdk.sh`，再在构建 Shell 中 `source scripts/ydlidar-sdk-env.zsh` 后重新构建。 |
| 启动时提示找不到 `libydlidar_sdk.so` | 在新 Shell 加载 SDK 环境脚本，或从仓库根目录使用 `./scripts/run-tracking.sh`。检查 `$YDLIDAR_SDK_PREFIX/lib/libydlidar_sdk.so` 是否存在。 |
| 没有 `/scan` 或融合服务报告没有扫描发布者 | 查看 `ros2 topic info /scan -v` 和 `ros2 topic hz /scan`；检查 `ydlidar/config/ydlidar.yaml` 中串口设备与驱动启动错误。 |
| 融合服务等待 `camera <- laser_link` | 运行 `ros2 run tf2_ros tf2_echo camera laser_link`；检查 `robot_bringup/config/platform.yaml` 和 `object_track/config/object_track.yaml` 的 frame 名称一致。 |
| Follow 被拒绝或扫描超时 | 读取服务响应；分别检查 `/camera/image_det`、`/ai_msg_det`、`/scan` 和 TF。先启用融合，并确认扫描持续更新后再启用 Follow。扫描停止时跟踪器会清理距离并请求零命令。 |
| 启动报 Foxglove Bridge 包不可用 | 若当前不需要 Foxglove，使用 `with_foxglove:=false` 启动。 |

## English operator guide

This guide covers installation, startup, debugging, and safe operation of the fixed tracking composition. Use `tracking.launch.py` for daily startup; control LiDAR Fusion and Follow separately through their runtime services.

### First-time SDK installation and build

First follow the [detector setup guide](../rknn_yolov6/README.md) to install compatible RKNN runtime and Rockchip MPP/RGA development libraries, and keep the official `rknn_api.h` outside the repository. The current board uses `$HOME/sdk/rknn/include`. Then install the persistent YDLIDAR SDK and build the hardware composition:

```bash
cd ~/code/ros-robot
./scripts/install-ydlidar-sdk.sh
source /opt/ros/foxy/setup.bash
source scripts/ydlidar-sdk-env.zsh
./scripts/colcon.sh build --symlink-install --packages-up-to robot_bringup \
  --parallel-workers 1 --cmake-args -DBUILD_TESTING=OFF \
  -DRKNN_API_INCLUDE_DIR="$HOME/sdk/rknn/include"
source ros2_ws/install/setup.bash
```

The command builds hardware runtime targets one package at a time to reduce compiler memory pressure on the Orange Pi. Run development tests using the package test instructions. Adjust `RKNN_API_INCLUDE_DIR` to the actual external header directory.

The installer places the pinned SDK under `$HOME/.local/opt/ydlidar-sdk/1.2.7` by default and uses a temporary directory outside the repository for source and build files. Set `YDLIDAR_SDK_PREFIX` before installation only when choosing another persistent prefix. Keep the SDK and generated build output out of Git source.

Load ROS, the SDK environment, and the workspace in each new shell. Zsh users should use Foxy and workspace `setup.zsh` files in place of `setup.bash`; `ydlidar-sdk-env.zsh` can be sourced by Bash or Zsh. `scripts/run-tracking.sh` loads the environments for this checkout.

### Start the fixed composition

The current Orange Pi Foxy environment has no `foxglove_bridge` package. Start from the repository root with the optional Bridge excluded:

```bash
./scripts/run-tracking.sh with_foxglove:=false
```

This thin wrapper loads Foxy, this checkout's `ros2_ws/install`, and the persistent SDK environment, then hands off directly to `ros2 launch robot_bringup tracking.launch.py`. It forwards command-line arguments unchanged.

You can also launch directly from a shell with the environment loaded:

```bash
cd ~/code/ros-robot
source /opt/ros/foxy/setup.bash
source scripts/ydlidar-sdk-env.zsh
source ros2_ws/install/setup.bash
ros2 launch robot_bringup tracking.launch.py with_foxglove:=false
```

The only launch argument is `with_foxglove`, which defaults to `true`. Once a Bridge compatible with the current ROS version is installed, omit the argument or enable it explicitly:

```bash
./scripts/run-tracking.sh with_foxglove:=true
# Or launch directly:
ros2 launch robot_bringup tracking.launch.py with_foxglove:=true
```

The fixed composition handles the daily camera, detection, lidar, platform TF, and tracking pipeline. The Agent, Voice, and Web video demo has a separate entry point. Do not pass `mode` or per-module switches; this launch does not support them.

### Observe through an existing ROSBridge

The current board has `rosbridge_server` installed. Start it in a separate terminal with the ROS environment loaded:

```bash
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

Choose a ROSBridge connection in the browser or Foxglove, using `ws://<board IP>:9090`, and view `/camera/image_det_track` and `/scan`. Keep `with_foxglove:=false` for the composition. ROSBridge belongs to its own terminal and is separate from the six processes in the fixed composition.

### Enable Fusion and Follow

LiDAR Fusion starts disabled and Follow starts in standby. Check that scans, camera detection inputs, and platform TF are available:

```bash
ros2 topic hz /scan
ros2 topic hz /camera/image_det
ros2 topic hz /ai_msg_det
ros2 run tf2_ros tf2_echo camera laser_link
```

Enable LiDAR Fusion first. After its service reports success, enable Follow:

```bash
ros2 service call /tracking/set_lidar_enabled std_srvs/srv/SetBool "{data: true}"
ros2 service call /tracking/set_enabled std_srvs/srv/SetBool "{data: true}"
```

If a service returns `success: false`, use its message to check the missing dependency before retrying. Follow requires synchronized image and detection inputs, a valid `camera <- laser_link` transform, enabled Fusion, and a recent `/scan`. The nodes do not enable these prerequisites automatically.

To stop, disable Follow before disabling Fusion:

```bash
ros2 service call /tracking/set_enabled std_srvs/srv/SetBool "{data: false}"
ros2 service call /tracking/set_lidar_enabled std_srvs/srv/SetBool "{data: false}"
```

Disabling Fusion clears the tracker's scan and range state. If Follow is still enabled, the tracker returns it to standby and emits a zero command. This does not stop or take ownership of the YDLIDAR driver.

### Safety and process lifecycle

`object_track/config/object_track.yaml` defaults to `dry_run: true`. In this mode the tracker logs command previews and does not create or publish `Twist` messages on `/tracking/cmd_vel_safe`. Keep this setting for routine startup and acceptance work.

ROS Launch manages the processes started by this launch. Ctrl-C shuts down those processes. A node exit does not trigger an automatic restart or stop ROS processes started in another shell. The operator diagnoses the cause and restarts the affected process.

Treat Foxglove as an observer; disconnecting its browser client is not a request to stop ROS Launch. During board acceptance, disconnect and reconnect Foxglove and confirm `/scan` continues to update, then record the observed result. See the [board acceptance report](../../../docs/reports/tracking-orange-pi-2026-10-13.md) for verified and skipped scenarios.

### Troubleshooting

| Symptom | Check and action |
|---|---|
| Build cannot find `ydlidar_sdk` or `ydlidar_sdkConfig.cmake` | Run `./scripts/install-ydlidar-sdk.sh`, then source `scripts/ydlidar-sdk-env.zsh` in the build shell and rebuild. |
| Startup cannot find `libydlidar_sdk.so` | Source the SDK environment in the new shell, or start from the repository root with `./scripts/run-tracking.sh`. Check that `$YDLIDAR_SDK_PREFIX/lib/libydlidar_sdk.so` exists. |
| No `/scan`, or Fusion reports no scan publisher | Check `ros2 topic info /scan -v` and `ros2 topic hz /scan`; inspect the serial device and driver errors in `ydlidar/config/ydlidar.yaml`. |
| Fusion waits for `camera <- laser_link` | Run `ros2 run tf2_ros tf2_echo camera laser_link`; check that frame names agree in `robot_bringup/config/platform.yaml` and `object_track/config/object_track.yaml`. |
| Follow is refused or scans expire | Read the service response; check `/camera/image_det`, `/ai_msg_det`, `/scan`, and TF separately. Enable Fusion first and confirm scans continue before enabling Follow. When scans stop, the tracker clears the range and requests a zero command. |
| Launch reports that Foxglove Bridge is unavailable | Start with `with_foxglove:=false` when Foxglove is not needed. |

## Independent module debugging / 独立模块调试

Load Foxy, the SDK environment, and the workspace in each terminal, then launch only the package being debugged:

```bash
ros2 launch usb_camera usb_camera.launch.py
ros2 launch img_decode img_decode.launch.py
ros2 launch rknn_yolov6 rknn_yolov6.launch.py
ros2 launch ydlidar ydlidar.launch.py
ros2 launch robot_bringup platform_tf.launch.py
ros2 launch object_track object_track.launch.py
```

`object_track` alone requires image, detection, scan, and TF inputs from other processes. Package launches do not start the rest of the fixed composition.

## Configuration ownership / 配置归属

Hardware, topics, model paths, and algorithm parameters belong to their package YAML files. After changing configuration, rebuild and source the workspace so the install-space files are current. Keep model weights outside the repository.

| Configuration file | Ownership / 负责内容 |
|---|---|
| `usb_camera/config/usb_camera.yaml` | Camera device, image topic, frame, resolution, frame rate, and capture cadence / 相机设备、图像话题、坐标系、分辨率、帧率与采集分频 |
| `img_decode/config/img_decode.yaml` | Compressed input, decoded output, resize ratio, and decode cadence / 压缩输入、解码输出、缩放比例与解码分频 |
| `rknn_yolov6/config/rknn_yolov6.yaml` | Model path, detection topic, thresholds, and inference options / 模型路径、检测话题、阈值与推理选项 |
| `ydlidar/config/ydlidar.yaml` | Serial device, scan frame, range, and driver parameters / 串口设备、扫描坐标系、量程与驱动参数 |
| `robot_bringup/config/platform.yaml` | Camera/lidar frames and static extrinsics / 相机与雷达坐标系及静态外参 |
| `object_track/config/object_track.yaml` | Topics, TF frames, dry-run, control parameters, and scan timeout / 话题、TF 坐标系、dry-run、控制参数与扫描超时 |
