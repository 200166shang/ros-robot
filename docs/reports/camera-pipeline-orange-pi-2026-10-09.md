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

## 物理相机上限探测

用 `v4l2-ctl --list-formats-ext` 查询 Logitech `046d:0825` 的模式表，当前设备列出的最高档位为 30 FPS；目标模式 1280×720 MJPEG 也只列出 30 FPS。随后用 `usb_camera_node` 固定 1280×720，分别请求 30 和 60 FPS，并用 `ros2 topic hz --window 100 /image_raw/compressed` 测量稳定输出：

| 请求帧率 | 实测相机发布 |
|---:|---:|
| 30 FPS | 约 29.8 FPS |
| 60 FPS | 约 29.8 FPS |

请求 60 FPS 时，运行中的 `v4l2-ctl --get-parm` 仍报告 30 FPS，因此请求值没有让摄像头超过模式上限。当前整条实体相机链路的最高已验证值仍是 MPP/RGA 解码输出约 29.79 FPS，基本贴近摄像头上限；继续把相机请求值调到 90 或 120 FPS 不会提高当前配置的端到端速率。

本轮开始时自动曝光优先级为开启，低光画面下曝光为 41.9 ms，实测约 24.1 FPS。为了测模式上限，临时关闭了 `exposure_auto_priority`；30 和 60 FPS 请求随后都达到约 29.8 FPS。测试结束后已恢复该控制为开启。自动曝光优先级可能为画面亮度延长曝光并降低 FPS，因此报告帧率时应同时记录曝光控制状态。一次 `camera_bench` 独立测量未能在 15 秒内取得首帧；本次上限数据改由 `usb_camera_node` 和 ROS 话题频率测量取得。

## 多解码节点高负载观察

为观察并发解码负载的影响，在相同的 1280×720 MJPEG、约 29.8 FPS 相机输入下，同时运行 4 个 OpenCV `img_decode_node`，分别发布到独立输出话题；`image_monitor` 只监控其中一个输出。相机端保持约 29.8 FPS 采集和发布，没有因增加解码节点而明显降速。单解码器基线的监控输出约为 11.4 FPS；四个解码器并发时，被监控解码器整体读数约为 1.7 FPS，观察窗口间曾在约 0.7–2.3 FPS 波动，显示解码输出受到明显 CPU 竞争。

这不是空闲系统的纯对比：测试期间原本运行的 `rosbridge_websocket` 也订阅压缩图像，并占用约 60–68% CPU；四个解码进程各约占 60–75% CPU，4 核系统负载均值约为 5.9–6.5。因此结果只说明该设备在当前背景负载和 OpenCV 软件解码下，增加并发解码节点会显著压低每个节点的输出速率，不能代表 MPP/RGA 后端或无 rosbridge 背景负载时的性能。测试结束后停止了本轮启动的进程，并将 `exposure_auto_priority` 恢复为 `1`。

可按下面步骤复测并发负载。先单独启动相机：

```zsh
ros2 launch usb_camera usb_camera.launch.py
```

在四个终端分别启动解码节点，每个都使用独立输出话题：

```zsh
ros2 run img_decode img_decode_node --ros-args -p lazy:=false -p output_topic:=/camera/stress_1
ros2 run img_decode img_decode_node --ros-args -p lazy:=false -p output_topic:=/camera/stress_2
ros2 run img_decode img_decode_node --ros-args -p lazy:=false -p output_topic:=/camera/stress_3
ros2 run img_decode img_decode_node --ros-args -p lazy:=false -p output_topic:=/camera/stress_4
```

另开终端监控其中一路解码输出，并同时记录相机日志和 CPU 负载：

```zsh
ros2 run img_decode image_monitor --ros-args -p topic:=/camera/stress_1
uptime
```

预热约 8 秒后观察至少 20 秒；结束时在五个节点终端分别按 `Ctrl+C`。测试 OpenCV 和 MPP/RGA 时分别重建 `img_decode`，并记录后端、相机 FPS、各路解码 FPS、系统负载和其它常驻订阅节点。不要在报告中把单路监控值当作四路总吞吐量。

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

要探测相机是否能超过默认 30 FPS，先停止相机和解码 launch，再查看设备模式并请求 60 FPS：

```zsh
v4l2-ctl -d /dev/video0 --list-formats-ext
ros2 run usb_camera usb_camera_node --ros-args \
  -p device:=/dev/video0 -p width:=1280 -p height:=720 \
  -p fps:=60 -p lazy:=false
```

另开终端运行 `ros2 topic hz --window 100 /image_raw/compressed`，并在相机运行时检查 `v4l2-ctl -d /dev/video0 --get-parm` 返回的帧率。模式表或驱动若仍显示 30 FPS，持续测量也约为 30 FPS，则更高请求已被设备上限截住。`fps` 是请求值，不保证设备实际采用；曝光自动优先级也可能因低光而降低帧率。若临时将 `exposure_auto_priority` 设为 `0` 做受控比较，结束后恢复为原值，并检查图像亮度。

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
