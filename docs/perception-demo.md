# Orange Pi ROS 2 视觉与安全跟踪 Demo

## 已迁移的链路

```text
Logitech C270 (/dev/video0, MJPEG 1280x720@30)
  -> usb_camera (/image_raw/compressed)
  -> img_decode (/camera/image_raw, rgb8)
  -> rknn_yolov6 (/ai_msg_det, /camera/image_det)
  -> object_track (/tracking/cmd_vel_safe)
  -> robot_agent (/agent/command, /agent/response)
```

`/tracking/cmd_vel_safe` 是跟踪节点在 live 模式下配置的输出 topic。默认
`dry_run=true` 时，节点只在日志中记录角速度建议，不创建 Twist publisher，也不向该 topic
发送消息；命中、丢失和超时的输出都经过同一个 dry-run 门。只有显式设置 `dry_run=false`
才会发布 Twist。当前仓库没有底盘/电机消费者，但这不代表仓库外或未来系统不存在；没有
完成消费者审查和硬件安全验收前，不要关闭 dry-run。线速度目前固定为 0；
当前 JPEG 解码采用 OpenCV 可靠后端；
RKNN 推理使用 RK3566 NPU。原项目的 MPP 解码器存在初始化失败后继续运行、固定缓冲区
越界风险和输出帧引用错误，因此没有将这段不安全实现直接带入演示链路。

## 同步与构建

Orange Pi `/home/orangepi/code/ros-robot` 是代码的唯一开发工作区；Mac 上的 Codex
通过 SSH 操作板端，Obsidian 保存学习记录。源码通过 Orange Pi 上的 Git 提交/推送，
不再把 Mac 目录当作代码镜像，也不通过 SCP 同步源码。通用网络与 SSH 操作见独立的
`oragnepi-pratice` 仓库。

```sh
# [Orange Pi; Foxy setup must run in Bash even if the login shell is zsh]
bash --noprofile --norc <<'BASH'
cd /home/orangepi/code/ros-robot/ros2_ws
source /opt/ros/foxy/setup.bash
colcon --log-base log build --base-paths src \
  --build-base build --install-base install --executor sequential \
  --cmake-args -DRKNN_API_INCLUDE_DIR=/home/orangepi/sdk/rknn/include
source install/setup.bash

# [Orange Pi] 单元测试（不启动相机节点）
colcon --log-base log test --base-paths src --build-base build --install-base install
colcon test-result --test-result-base build --verbose
BASH
```

## 一键启动

```sh
# [Orange Pi]
bash --noprofile --norc <<'BASH'
cd /home/orangepi/code/ros-robot/ros2_ws
source /opt/ros/foxy/setup.bash
source install/setup.bash
ros2 launch robot_bringup person_tracking_demo.launch.py \
  model_path:=/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn \
  input_wav_path:=/home/orangepi/local-data/ros-robot/voice-fixtures/start_person_tracking_zh_2026-09-24.wav
BASH
```

该 launch 会占用 `/dev/video0`，并启动多个 ROS 节点。运行前先确认旧工作区的跟踪演示已
停止；不能同时启动两套相机链路。若 WAV 样本不在本机，先准备已授权的单声道 16 kHz PCM16
文件并覆盖 `input_wav_path`。不接实体扬声器时，TTS 仍只做文件生成/软件验证。

看到以下日志即代表关键硬件初始化成功：

- `opened /dev/video0 as MJPEG 1280x720`
- `RKNN runtime=1.4.0 driver=0.9.6`
- `RKNN YOLOv6 ready: model=640x352 labels=80`
- 周期性的 `capture ... fps` 和 `inference ... fps`

## 保存检测画面

保持 launch 终端运行，另开一个终端：

```sh
# [Orange Pi]
bash
source /opt/ros/foxy/setup.bash
source /home/orangepi/code/ros-robot/ros2_ws/install/setup.bash
ros2 run img_decode image_monitor --ros-args \
  -p topic:=/camera/image_det \
  -p snapshot_path:=/home/orangepi/local-data/ros-robot/artifacts/detection_snapshot.jpg
```

看到 `snapshot ... saved` 后按 Ctrl-C。可从 Mac 取回：

```sh
# [Mac]
rsync -avP orangepi3b:/home/orangepi/local-data/ros-robot/artifacts/detection_snapshot.jpg .
```

## 浏览器实时画面

总 launch 默认同时启动网页节点。在 Mac 浏览器尝试直接打开：

```text
http://<BOARD_IP>:8080
```

页面可以切换检测画面和原始画面，并可安全地启停跟踪及摄像头。如果 Mac 的 VPN、
本地网络权限或代理阻止直接访问局域网端口，建立 SSH 隧道：

```sh
# [Mac] 保持此终端运行
ssh -N -L 18080:127.0.0.1:8080 orangepi3b
```

然后打开：

```text
http://127.0.0.1:18080
```

如果使用命令行验证且 Mac 设置了全局 HTTP 代理，应绕过代理：

```sh
# [Mac]
curl --noproxy '*' http://127.0.0.1:18080/healthz
```

网页服务只监听本机局域网端口，没有登录认证，不应通过路由器映射到公网。

## Agent 命令和安全跟踪

自动验收探针会发送 `start_tracking`、注入合成检测框，并验证 Agent 响应、`/rosout` 中
的 `object_track` dry-run 预览，以及运动 topic 收到 **0 条 Twist**。探针会通过 Agent
开启摄像头/跟踪；只能在独立 ROS domain 的测试环境使用，不要对日常运行中的 ROS graph
直接执行：

```sh
# [Orange Pi；先启动同一 ROS_DOMAIN_ID 的测试节点]
export ROS_DOMAIN_ID=74
ros2 run robot_bringup acceptance_probe.py
```

预期输出包含 `dry_run_previews=[...]`、`motion_topic_messages=[]`，结尾为
`acceptance=PASS`。dry-run 预览应从节点日志或 `/rosout` 观察；不要期待
`/tracking/cmd_vel_safe` 发布 Twist。

```sh
# [Orange Pi] 行为命令示例：会启用 Agent 的相机和跟踪；只在隔离测试域执行
ros2 topic pub --once /agent/command std_msgs/msg/String "{data: start_tracking}"

# [Orange Pi] dry_run=true 时看 object_track 日志中的预览；此 topic 不应收到 Twist
ros2 topic info /tracking/cmd_vel_safe

# [Orange Pi] 查询 Agent 状态
ros2 topic pub --once /agent/command std_msgs/msg/String "{data: status}"
ros2 topic echo /agent/response

# [Orange Pi] 停止跟踪
ros2 topic pub --once /agent/command std_msgs/msg/String "{data: stop_tracking}"

# [Orange Pi] 停止/恢复摄像头
ros2 topic pub --once /agent/command std_msgs/msg/String "{data: stop_camera}"
ros2 topic pub --once /agent/command std_msgs/msg/String "{data: start_camera}"
```

人物在画面左、右移动时，`angular.z` 应改变符号；居中时接近 0；人物离开或停止
跟踪后应发布全零速度。

## 当前边界

- 未接串口、电机和雷达，因此不发布真实底盘 `/cmd_vel`。
- 不包含 Nav2、真实里程计、急停协议或电机闭环验收。
- Agent 只执行固定白名单命令，不调用 shell、云端模型或硬件控制接口。
- C270 的个别 MJPEG 帧会让 libjpeg 输出 `extraneous bytes` 警告；实测帧仍可解码，
  NPU 链路持续运行。后续可另行实现并严格验收新的 MPP/RGA 后端。
