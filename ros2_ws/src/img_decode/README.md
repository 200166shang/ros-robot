# img_decode 使用说明

`img_decode_node` 订阅 `sensor_msgs/msg/CompressedImage` JPEG 图像，解码并缩放后发布 `sensor_msgs/msg/Image`（`rgb8`）。节点会保留输入消息的 header。

默认数据流如下：

```text
/image_raw/compressed  -- JPEG -->  img_decode_node  -- rgb8 -->  /camera/image_raw
```

## 环境与构建

以下命令在仓库根目录运行。当前终端使用 Zsh 时加载 `setup.zsh`：

```zsh
source /opt/ros/foxy/setup.zsh
cd ros2_ws
colcon build --packages-select usb_camera
colcon build --packages-select img_decode --cmake-args -DIMG_DECODE_BACKEND=AUTO
source install/setup.zsh
```

这里分别构建相机发布器和解码器，因为 `camera_decode.launch.py` 会启动这两个包中的节点。在不需要相机 launch 的环境中，只构建 `img_decode` 即可。

后端在构建时选择：

| `IMG_DECODE_BACKEND` | 行为 | 适用环境 |
|---|---|---|
| `AUTO`（默认） | ARM64 选择 Rockchip MPP/RGA，其它架构选择 OpenCV | 按目标平台自动选择 |
| `OPENCV` | OpenCV 软件 JPEG 解码与缩放 | 普通开发机，或 Orange Pi 软件路径 |
| `ROCKCHIP` | Rockchip MPP 解码与 RGA 缩放 | 安装了 MPP/RGA 开发头文件和库的 Rockchip 设备 |

例如在 Orange Pi 上明确构建硬件后端：

```zsh
colcon build --packages-select img_decode --cmake-args -DIMG_DECODE_BACKEND=ROCKCHIP
source install/setup.zsh
```

明确构建 OpenCV 软件后端时，将值改为 `OPENCV`。启动日志会打印实际选用的后端。更换后端后应重新构建并重新 source 工作区。

## 使用相机运行完整数据流

工作区已构建 `usb_camera` 和 `img_decode` 并 source 后，在一个终端启动相机与解码节点：

```zsh
ros2 launch img_decode camera_decode.launch.py
```

此 launch 会启动 `/dev/video0` 上的 `usb_camera_node` 和 `img_decode_node`。相机默认请求 MJPEG 1280×720、30 FPS，并发布到 `/image_raw/compressed`；解码器默认缩放到 640×360 并发布到 `/camera/image_raw`。启动时如果看到 `decoder subscribed`，表示解码器已订阅输入；若没有输出订阅者，默认的 `lazy` 行为会暂停输入订阅。

在另一个已加载 ROS 2 与工作区环境的 Zsh 终端查看解码输出帧率：

```zsh
source /opt/ros/foxy/setup.zsh
source ros2_ws/install/setup.zsh
ros2 topic hz /camera/image_raw
```

Run these commands from the repository root. In each new terminal, source both the ROS installation and this workspace before using ROS commands.

`ros2 topic hz` 自身会订阅输出话题，因此也会唤醒 lazy 解码器和相机。刚启动时短暂出现 `topic does not appear to be published yet` 可能只是尚未收到第一帧；持续无输出时检查相机节点、输入话题和解码器日志。另开终端可以查看图像消息的尺寸、编码和 header：

```zsh
ros2 topic echo /camera/image_raw --no-arr
```

`--no-arr` 会隐藏很长的像素数组，只显示尺寸、编码和 header 等字段。Foxy 的 `ros2 topic echo` 不支持 `--once` 参数，收到一帧后按 `Ctrl+C` 停止。

## 单独检查输出图像与帧率

`image_monitor` 会订阅输出图像，检查 `rgb8` 编码和 buffer/stride，并每隔约 5 秒打印自启动以来的平均 FPS 和帧数。可选的 `snapshot_path` 会将第一张有效图像保存为文件：

```zsh
ros2 run img_decode image_monitor --ros-args \
  -p topic:=/camera/image_raw \
  -p snapshot_path:=/tmp/img_decode.png
```

它会建立输出订阅，因此同样可用于触发默认 lazy 数据流。停止后检查截图：

```zsh
file /tmp/img_decode.png
```

`image_monitor` 用于观察输出图像和帧率，不会记录 CSV，也不测量单帧纯解码耗时。需要看话题实时频率时也可以使用 `ros2 topic hz /camera/image_raw`。

## Orange Pi 端到端预览和速率验证

在 Orange Pi 上按需选择后端并重新构建 `img_decode`。`usb_camera` 也需要构建；运行编码器往返时还要构建 `img_encode`：

```zsh
cd ros2_ws
colcon build --packages-select usb_camera
colcon build --packages-select img_decode --cmake-args -DIMG_DECODE_BACKEND=ROCKCHIP
colcon build --packages-select img_encode --cmake-args -DIMG_ENCODE_BACKEND=MPP
source install/setup.zsh
```

软件路径将两个后端值都改成 `OPENCV`。在一个终端启动物理相机和解码器：

```zsh
ros2 launch img_decode camera_decode.launch.py
```

相机默认以 1280×720 MJPEG、请求 30 FPS 运行；解码输出默认缩放为 640×360。预览使用工作区内的 RViz2 预设。它订阅 `/camera/image_raw`，并采用与图像发布器匹配的 Best Effort QoS：

```zsh
cd ..
ROBOT_RVIZ2_CONFIG="$PWD/ros2_ws/src/img_decode/config/camera_preview.rviz" \
  scripts/rviz2-headless.sh start
scripts/rviz2-headless.sh status
```

headless RViz2 和 Mac noVNC SSH 隧道的安装及连接步骤见 [`ydlidar/README.md`](../ydlidar/README.md) 的 noVNC 章节。预览结束后运行 `scripts/rviz2-headless.sh stop`，再在相机 launch 终端按 `Ctrl+C`。相机与解码器也可以在预览期间继续运行。

速率观测时，先等待相机首帧和约 8 秒预热，再观察约 10 秒。`usb_camera_node` 每 5 秒报告实际采集 FPS 和发布 FPS；启动 `image_monitor` 可观察解码输出 FPS，也可分别在终端中用 `ros2 topic hz /image_raw/compressed` 和 `ros2 topic hz /camera/image_raw` 查看话题频率。测 ROS 消息带宽时，在另外两个终端运行 `ros2 topic bw --window 20 /image_raw/compressed` 和 `ros2 topic bw --window 20 /camera/image_raw`；每个新终端先 source ROS 和工作区。`bw` 每秒报告最近 20 条消息的带宽和平均大小，建议预热后记录 3–5 次稳定读数。它测量订阅端收到的 ROS 消息数据速率，不代表网络接口总流量。报告中应记录实际后端、测量窗口、采集/相机发布/解码输出 FPS 和带宽，不设置固定 FPS 门槛。

要核对帧分频，先停止组合 launch，再将相机发布器单独设为 divider 2，并独立运行默认 decoder：

```zsh
ros2 launch usb_camera usb_camera.launch.py frame_divider:=2
```

另开终端启动 decoder：

```zsh
ros2 run img_decode img_decode_node
```

在其它终端订阅 `/camera/image_raw`（例如运行 `ros2 topic hz /camera/image_raw`）以唤醒 lazy decoder。相机日志中的采集 FPS 应约为未分频值，发布 FPS 应约为其一半；解码输出 FPS 应跟随压缩输入话题。不要同时运行 `camera_bench`，因为它会独占打开相同的 V4L2 设备。

JPEG 编码到 ROS 解码的端到端往返命令见 [`img_encode/README.md`](../img_encode/README.md)。验证 OpenCV 和 MPP/RGA 时分别重建对应后端，并在报告中排除编码器 FPS、延迟和资源用量。

## 独立运行解码器或调整参数

如果压缩图像已由其它节点发布，可单独启动解码器：

```zsh
ros2 run img_decode img_decode_node
```

直接运行节点时可用 ROS 参数覆盖默认值。例如，将缩放设为 0.75、每 2 个输入处理 1 帧：

```zsh
ros2 run img_decode img_decode_node --ros-args \
  -p scale:=0.75 \
  -p frame_divider:=2
```

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `input_topic` | `/image_raw/compressed` | `CompressedImage` 输入话题 |
| `output_topic` | `/camera/image_raw` | `rgb8` 输出话题 |
| `scale` | `0.5` | 宽、高的缩放比例，必须在 `(0, 1]` |
| `frame_divider` | `1` | 按收到的压缩输入计数，每 N 帧处理一帧；小于 1 时按 1 处理 |
| `width` | `1280` | Rockchip 解码输出缓冲区的最大配置宽度，范围 `[1, 8192]` |
| `height` | `720` | Rockchip 解码输出缓冲区的最大配置高度，范围 `[1, 8192]` |
| `lazy` | `true` | 没有输出订阅者时暂停输入订阅 |

`camera_decode.launch.py` 使用相机和解码器的默认参数。要自定义解码器参数，请单独启动相机，再用 `ros2 run img_decode img_decode_node --ros-args -p name:=value` 启动解码器；例如先在一个终端运行 `ros2 launch usb_camera usb_camera.launch.py`，再在另一个终端运行上面的解码命令。`width` 和 `height` 主要用于配置 Rockchip 后端缓冲区，不会覆盖输入图像的实际尺寸；实际输出尺寸由输入尺寸乘以 `scale` 决定。

## img_decode usage

`img_decode_node` converts compressed JPEG images on `/image_raw/compressed` into `rgb8` images on `/camera/image_raw`, preserving the input header. Run `ros2 launch img_decode camera_decode.launch.py` to start the camera and decoder together, then use `ros2 topic hz /camera/image_raw` or `ros2 run img_decode image_monitor` to check output. The Chinese guide above gives the Zsh build steps, backend choices, snapshot example, and all parameter defaults and constraints. For custom node parameters, start `usb_camera` separately and pass ROS parameter overrides to `img_decode_node`.

For Orange Pi preview and full-pipeline rate validation, use the RViz2 camera preset and noVNC workflow in the Chinese guide above. Repeat the run with both `IMG_DECODE_BACKEND=OPENCV` and `ROCKCHIP`.
