# rknn_yolov6 使用说明

`rknn_yolov6` 订阅 ROS 2 RGB 图像，运行目标检测，并发布检测消息和带框图像。ROS 话题与消息接口由节点统一管理，推理和后处理后端在构建时选择 RKNN/RGA 或 Haar。

## 数据流

```text
USB 相机
  └─ /image_raw/compressed (sensor_msgs/msg/CompressedImage, JPEG)
       └─ img_decode
            └─ /camera/image_raw (sensor_msgs/msg/Image, rgb8)
                 └─ rknn_yolov6
                      ├─ /ai_msg_det (robot_interfaces/msg/Dets)
                      └─ /camera/image_det (sensor_msgs/msg/Image, rgb8)
```

| 用途 | 话题 | 类型 | 说明 |
|---|---|---|---|
| 输入图像 | `/camera/image_raw` | `sensor_msgs/msg/Image` | 要求 `rgb8` 编码 |
| 检测结果 | `/ai_msg_det` | `robot_interfaces/msg/Dets` | 包含图像尺寸、类别、置信度和框坐标 |
| 标注图像 | `/camera/image_det` | `sensor_msgs/msg/Image` | RGB 原图上绘制检测框和类别置信度 |
| 启停控制 | `/enable_detector` | `std_msgs/msg/Bool` | `false` 暂停接收检测帧，`true` 恢复 |

package launch 默认 `always_process=true`，即使观察端没有订阅者也持续处理输入；直接运行节点时参数默认仍为 `false`。标注图像只在有订阅者时发布。队列容量为 2，队列已满时丢弃最旧帧，以减少实时处理延迟。

## 构建

### RKNN/RGA 后端（Orange Pi / AArch64）

设备需安装 ROS 2 Foxy、RKNN runtime、RGA 头文件与库，以及与 runtime 兼容的官方 `rknn_api.h`。SDK 头文件、模型权重和运行时库不放入仓库。已验证的 RKNN runtime 1.4.0 对应头文件可从 [Rockchip rknpu2 v1.4.0](https://github.com/airockchip/rknpu2/blob/v1.4.0/runtime/RK356X/Linux/librknn_api/include/rknn_api.h) 获取。

以下命令从仓库根目录运行；构建和安装输出放在 `/tmp`：

```zsh
source /opt/ros/foxy/setup.zsh
cd ~/code/ros-robot
./scripts/colcon.sh --log-base /tmp/ros-robot-rknn-log build \
  --base-paths src --packages-up-to rknn_yolov6 \
  --build-base /tmp/ros-robot-rknn-build \
  --install-base /tmp/ros-robot-rknn-install \
  --cmake-args -DRKNN_YOLOV6_BACKEND=RKNN \
  -DRKNN_API_INCLUDE_DIR=/path/to/rknn/include
```

### Haar 后端（普通开发机或接口验证）

```zsh
source /opt/ros/foxy/setup.zsh
cd ~/code/ros-robot
./scripts/colcon.sh --log-base /tmp/ros-robot-haar-log build \
  --base-paths src --packages-up-to rknn_yolov6 \
  --build-base /tmp/ros-robot-haar-build \
  --install-base /tmp/ros-robot-haar-install \
  --cmake-args -DRKNN_YOLOV6_BACKEND=HAAR
```

`RKNN_YOLOV6_BACKEND=AUTO` 会在 AArch64 选择 RKNN，在其它架构选择 Haar。Haar 模式需要外部 Haar cascade 文件；它是备用检测后端，不等同于 YOLOv6 模型。

## 启动完整相机检测链路

如果尚未构建相机和解码包，先构建一次。在仓库根目录执行：

```zsh
cd ~/code/ros-robot
source /opt/ros/foxy/setup.zsh
./scripts/colcon.sh build --packages-select usb_camera
./scripts/colcon.sh build --packages-select img_decode --cmake-args -DIMG_DECODE_BACKEND=ROCKCHIP
```

若系统没有 Rockchip MPP/RGA 开发库，将 `ROCKCHIP` 改为 `OPENCV`。每个新终端都要按顺序加载 ROS、相机工作区和检测器安装环境：

```zsh
source /opt/ros/foxy/setup.zsh
source ~/code/ros-robot/ros2_ws/install/setup.zsh
source /tmp/ros-robot-rknn-install/setup.zsh
```

**终端 1：启动 USB 相机**

```zsh
ros2 launch usb_camera usb_camera.launch.py
```

**终端 2：启动 JPEG 解码器**

```zsh
ros2 launch img_decode img_decode.launch.py
```

相机从 YAML 配置的设备发布压缩 JPEG；解码器将其转换为 `/camera/image_raw` 的 `rgb8` 图像。

**终端 3：启动检测节点**

```zsh
ros2 launch rknn_yolov6 rknn_yolov6.launch.py
```

RKNN 模型和 Haar cascade 是外部资源，需在设备上提供可读取的文件。通过修改 `rknn_yolov6/config/rknn_yolov6.yaml` 配置模型路径和算法参数；标签文件由 launch 从包内 `config/coco_labels.txt` 定位。修改 YAML 后重新构建并 source 工作区。

**终端 4：订阅检测结果并触发实时推理**

```zsh
ros2 topic echo /ai_msg_det
```

查看检测消息的发布频率可用 `ros2 topic hz /ai_msg_det`；这类订阅也会触发默认的按需检测。查看标注图像可使用已安装的 `rqt_image_view` 并选择 `/camera/image_det`。

也可以不依赖相机链路，单独发布符合要求的 `rgb8` 图像到 `input_topic`，再启动检测节点。

## 参数

常规 package launch 直接读取 `config/rknn_yolov6.yaml`，不提供 ROS 参数的 launch 命令行覆盖。持久配置请改 YAML，再重新构建并加载工作区。表中 YAML 参数可用于 detector 节点；标签路径由 launch 从包 share 目录注入：

| YAML 参数 | 默认值 | 说明 |
|---|---|---|
| `model_path` | `/home/orangepi/models/ros-robot/vision/yolov6n_85.rknn` | RKNN 模型路径；RKNN 后端必填，模型文件保存在仓库外 |
| `haar_cascade_path` | 空 | Haar 后端的 cascade 文件路径；资源文件保存在仓库外 |
| `input_topic` | `/camera/image_raw` | RGB 输入图像话题 |
| `detections_topic` | `/ai_msg_det` | 检测消息输出话题 |
| `annotated_topic` | `/camera/image_det` | 标注图像输出话题 |
| `confidence_threshold` | `0.30` | 候选检测置信度阈值 |
| `nms_threshold` | `0.30` | 非极大值抑制阈值 |
| `enabled` | `true` | 是否处理输入；可由 `/enable_detector` 动态切换 |
| `always_process` | `true`（package launch） | 为 `true` 时即使没有输出订阅者也处理实时图像；直接运行节点的默认值为 `false` |
| `print_perf_detail` | `false` | 为 `true` 时输出 RKNN runtime 的逐层性能详情 |
| `use_multi_npu_core` | `false` | 是否请求多 NPU 核心；是否支持取决于设备/runtime |
| `is_offline_image_mode` | `false` | 是否从图片目录离线处理 |
| `offline_images_path` | 空 | OpenCV 图片 glob，例如 `/data/images/*.jpg` |
| `offline_output_path` | 空 | 离线标注图像输出目录；其父目录需已存在 |

`enabled` 也可通过已有 `/enable_detector` Bool Topic 动态切换。控制节点启停示例：

```zsh
ros2 topic pub --once /enable_detector std_msgs/msg/Bool "{data: false}"
ros2 topic pub --once /enable_detector std_msgs/msg/Bool "{data: true}"
```

## 离线图片检测

离线模式会复用同一推理与后处理流程，将标注结果保存为按处理顺序编号的 JPG 文件（`0.jpg`、`1.jpg`……）。运行前在 `rknn_yolov6/config/rknn_yolov6.yaml` 中设置 `is_offline_image_mode: true`、`offline_images_path` 和 `offline_output_path`，然后重新构建并 source 工作区：

```yaml
rknn_yolov6:
  ros__parameters:
    is_offline_image_mode: true
    offline_images_path: "/data/images/*.jpg"
    offline_output_path: /tmp/rknn-yolov6-results
```

离线模式不要求检测结果订阅者；检测消息和标注图像仍会发布。`offline_output_path` 不存在时节点会尝试创建该目录，但不会递归创建缺失的父目录。

## 运行日志与数据记录

### 理解节点日志

- `RKNN runtime=... driver=...`：RKNN 初始化成功后打印的 runtime 和驱动版本。
- `rknn_set_core_mask: No implementation found for current platform`：部分平台/runtime 会在核心选择时打印此信息。若之后继续打印 runtime 版本和 `inference` 日志，说明节点继续运行；若节点随后退出，应结合后续错误和退出码判断。
- `inference X fps, detections=N`：每当处理线程完成一帧，且距离上次报告至少 5 秒时打印。`X` 是**节点启动以来已完成处理帧数除以节点启动以来经过的秒数**，包含没有输入帧或没有订阅者时的空闲时间；它不是最近 5 秒的帧率，也不是 RKNN 单次推理耗时。`N` 是本次报告对应的最近一帧检测框数量。
- `print_perf_detail: true`（detector YAML）：请求 RKNN runtime 输出逐层性能详情。它会增加日志量；不开启时不会打印 `RKNN perf detail`。

要观察实时话题频率，请在其它终端运行：

```zsh
ros2 topic hz /camera/image_raw
ros2 topic hz /ai_msg_det
```

`/camera/image_raw` 的频率反映检测器输入端收到的图像，`/ai_msg_det` 的频率反映检测结果发布速率。`/ai_msg_det` 的订阅本身会唤醒默认按需检测。纯 RKNN 推理耗时需使用 runtime 性能详情或单独在 `backend_->infer()` 周围计时；`inference X fps` 不能替代该数据。

### 保存控制台日志和 ROS 日志文件

Launch 默认将节点日志输出到控制台，ROS 日志文件默认保存在 `~/.ros/log/`。如需为一轮运行单独保存日志：

```zsh
mkdir -p /tmp/rknn-yolov6-logs
ROS_LOG_DIR=/tmp/rknn-yolov6-logs \
  ros2 launch rknn_yolov6 rknn_yolov6.launch.py \
  2>&1 | tee /tmp/rknn-yolov6-logs/console.log
```

### 录制 ROS 话题数据

需要复查输入和检测结果时，可使用 rosbag 录制相关话题：

```zsh
ros2 bag record -o /tmp/rknn-yolov6-run \
  /camera/image_raw /ai_msg_det /camera/image_det
```

录制 `/camera/image_raw` 和 `/camera/image_det` 会占用较多磁盘空间；请按需要选择话题并确认可用空间。订阅 `/camera/image_det` 也会使节点发布标注图像。

## 测试

包内测试覆盖后处理和 ROS 话题接口。话题测试发布合成 `rgb8` 图像，并检查检测消息和标注图像；测试使用外部 RKNN 模型/标签或 Haar cascade。离线用例还会检查标注图片是否写入。`RKNN_YOLOV6_TEST_IMAGE` 可指定离线测试图像。

RKNN 构建的示例：

```zsh
source /opt/ros/foxy/setup.zsh
source /tmp/ros-robot-rknn-install/setup.zsh
export RKNN_YOLOV6_TEST_MODEL=/path/to/yolov6.rknn
export RKNN_YOLOV6_TEST_LABELS="$PWD/ros2_ws/src/rknn_yolov6/config/coco_labels.txt"
export RKNN_YOLOV6_TEST_IMAGE=/path/to/test.jpg
cd /tmp/ros-robot-rknn-build/rknn_yolov6
ctest --output-on-failure
```

Haar 构建需设置 `RKNN_YOLOV6_TEST_CASCADE=/path/to/haarcascade_frontalface_default.xml`，并在对应 Haar 构建目录运行 `ctest --output-on-failure`。测试不启用跟踪控制或硬件动作。
