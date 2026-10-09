# Orange Pi 相机数据流验证报告 — 2026-10-09

Issue：[验证 Orange Pi 相机预览和 ROS 2 数据流速率 #19](https://github.com/200166shang/ros-robot/issues/19)

## 环境与方法

- Orange Pi 3B，AArch64 Rockchip RK356x，ROS 2 Foxy。
- UVC 实体摄像头：Logitech `046d:0825`，设备为 `/dev/video0`，配置为 1280×720 MJPEG，请求帧率 30 FPS。
- 解码缩放比例为 0.5，输出为 640×360 `rgb8`，话题为 `/camera/image_raw`。
- 速率探针以 Best Effort QoS 订阅 `/image_raw/compressed` 和 `/camera/image_raw`。每轮先预热 8 秒，再测量 10 秒。采集和相机发布 FPS 取自 `usb_camera_node` 每 5 秒输出的统计值。启动等待和一次摄像头重开均不计入测量窗口。
- RViz2 通过现有 headless noVNC 服务加载 `img_decode/config/camera_preview.rviz`。预览将 RViz 渲染速率限制为 5 FPS，并使用 Best Effort 图像 QoS。测量速率时关闭了 GUI，因为软件渲染会降低开发板上的数据处理速率。

## 测量结果

数据路径：`UVC 摄像头 → usb_camera → /image_raw/compressed → img_decode → /camera/image_raw → RViz2/noVNC`。

| 构建配置 | 摄像头采集 | 相机话题发布 | 解码输出 | 说明 |
|---|---:|---:|---:|---|
| OpenCV | 29.8 FPS | 29.79 FPS | 27.69 FPS | 实体摄像头经 OpenCV 解码 JPEG；RViz2/noVNC 显示了实时图像。 |
| Rockchip MPP/RGA | 29.8 FPS | 29.79 FPS | 29.79 FPS | 实体摄像头经 MPP 解码、RGA 缩放；RViz2/noVNC 显示了实时图像。 |
| MPP/RGA，`frame_divider=2` | 29.8 FPS | 14.88 FPS | 14.88 FPS | 按配置，相机发布和解码速率约为采集速率的一半。 |

未设定固定 FPS 门槛，也未与 ROS 1 比较。相机节点启动时偶尔报告采集超时并重新打开 `/dev/video0`；测量在摄像头开始输出帧且预热结束后进行。

## 数据解读

- OpenCV 路径中，相机发布约为采集速率的 99.97%；解码输出约为压缩输入的 92.95%，约少 2.10 FPS。表示这轮端到端测量中有一部分输入帧没有体现在解码输出速率上，不能仅据此判断具体丢帧位置。
- MPP/RGA 路径中，解码输出与相机发布速率在显示精度内相同。相较 OpenCV 这轮观测，输出速率高约 7.6%；这是整条流水线的帧率对比，不是单帧解码加速倍数。
- `frame_divider=2` 时，相机采集仍约 29.8 FPS，发布约 14.88 FPS，约为采集速率的 49.9%；解码输出跟随发布速率。这与每两帧发布一帧的配置相符。
- 以上 FPS 是稳定运行窗口里的端到端速率，不能换算成纯解码耗时。此次没有分别测量 JPEG 解码、缩放、ROS 发布各自的单帧耗时。

## ROS 话题带宽补充测量

使用 ROS 2 Foxy 的 `ros2 topic bw` 在本机同时订阅两个话题，窗口设为最近 20 条消息。下表取启动后的 3 次稳定输出的平均值；括号内为这 3 次输出的范围。

| OpenCV 路径话题 | 平均带宽 | 平均消息大小 | 观测范围 |
|---|---:|---:|---:|
| `/image_raw/compressed` | 约 0.985 MB/s | 约 31.76 KB | 0.973–0.997 MB/s |
| `/camera/image_raw` | 约 19.66 MB/s | 约 0.69 MB | 19.35–19.85 MB/s |

按本次观测，解码后的 RGB 话题带宽约为压缩 JPEG 话题的 20 倍。640×360 `rgb8` 每帧像素数据为 691,200 字节，与 `ros2 topic bw` 显示的约 0.69 MB/帧相符；JPEG 大小会随画面内容变化。带宽结果描述本机 ROS 订阅端收到的消息数据速率，不包含以太网链路封装开销，也不是网络接口总流量。

复现命令：

```bash
ros2 topic bw --window 20 /image_raw/compressed
ros2 topic bw --window 20 /camera/image_raw
```

两条命令应在数据流运行期间、分别在终端中执行。`ros2 topic bw` 给出订阅端收到的 ROS 消息序列化大小速率，不代表以太网链路总占用。以上补充测量使用 OpenCV 解码后端；没有为 MPP/RGA 路径补测带宽。

本次测量启动时相机曾发生一次采集超时并重开设备；OpenCV 解码日志也出现 libjpeg 关于 JPEG marker 前额外字节的警告。带宽均值取自恢复出帧后的连续稳定输出。

## 自行启动验证

以下步骤在 Orange Pi、ROS 2 Foxy 和 `/dev/video0` 摄像头上运行。先在仓库根目录构建所需包。软件路径使用 `OPENCV`；要测 Rockchip 硬件路径，将后端值换为 `ROCKCHIP`。

```zsh
source /opt/ros/foxy/setup.zsh
cd ros2_ws
colcon build --packages-select usb_camera
colcon build --packages-select img_decode --cmake-args -DIMG_DECODE_BACKEND=OPENCV
source install/setup.zsh
```

在终端 A 启动相机和解码器：

```zsh
source /opt/ros/foxy/setup.zsh
cd /path/to/ros-robot/ros2_ws
source install/setup.zsh
ros2 launch img_decode camera_decode.launch.py
```

再开四个终端分别运行以下四条命令。每个终端先 source ROS 与工作区；启动监测后等到首帧并预热约 8 秒，再记录稳定读数。若只看带宽，可只启动两个 `bw` 监测终端。

```zsh
ros2 topic hz /image_raw/compressed
ros2 topic bw --window 20 /image_raw/compressed
```

```zsh
ros2 topic hz /camera/image_raw
ros2 topic bw --window 20 /camera/image_raw
```

`bw` 会每秒更新最近 20 条消息的带宽和平均消息大小；建议记录 3–5 次稳定读数。相机日志提供采集与发布 FPS，`hz` 提供话题 FPS。把解码器启动日志中的后端、测量窗口和上述结果一起记下。没有订阅者时节点会采用 lazy 行为，因此 `hz`/`bw` 订阅者也会唤醒数据流。

要验证分频，先停止组合 launch，再在终端 A 启动分频相机：

```zsh
ros2 launch usb_camera usb_camera.launch.py frame_divider:=2
```

在终端 B 单独启动解码器，然后用前述 `hz` 命令订阅 `/image_raw/compressed` 和 `/camera/image_raw`：

```zsh
ros2 run img_decode img_decode_node
```

预期采集速率基本不变，相机发布和解码输出约为其一半。不要同时运行 `camera_bench`，它会独占摄像头。图像预览启动步骤见 [`img_decode/README.md`](../../ros2_ws/src/img_decode/README.md) 的 Orange Pi 端到端验证章节；JPEG 编码器往返验证见 [`img_encode/README.md`](../../ros2_ws/src/img_encode/README.md)。

## 编码器功能往返验证

每种后端都将生成的四象限 640×360 `rgb8` 图像发布给编码器。编码器在 `/camera/image_raw/compressed` 发布 `format: jpeg` 的消息，并保留输入 header；随后将消息送入缩放比例为 0.5 的 ROS 2 解码器。解码输出保留了 header，尺寸为 320×180、编码为 `rgb8`，且通过了四个颜色区域的内容检查。

- OpenCV：往返探针通过。
- MPP/RGA：往返探针通过。

未测量编码器 FPS、延迟或资源使用量，因此这些数据未纳入性能结论。

## 构建与测试证据

- OpenCV 配置：在 Orange Pi 上构建了 `usb_camera`、`img_decode` 和 `img_encode`；对应的 ROS 接口与指标测试分别通过 3、3、1 项。
- MPP/RGA 配置：使用已安装的 Rockchip MPP/RGA 库构建了 `img_decode` 和 `img_encode`；对应 ROS 测试分别通过 3 项和 1 项。运行日志确认使用 Rockchip MPP/RGA 后端及 RGA API 1.9.3。
- RViz2：图像面板显示了来自 `/camera/image_raw` 的实体场景，状态为 OK。noVNC 页面在本机回环地址返回 HTTP 200。
- `scripts/verify_image_encode_roundtrip.py` 提供并检查了编码器到解码器的 ROS 话题往返流程。
