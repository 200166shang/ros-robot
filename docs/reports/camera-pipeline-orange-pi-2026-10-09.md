# Orange Pi 相机数据流验证报告 — 2026-10-09

Issue：[验证 Orange Pi 相机预览和 ROS 2 数据流速率 #19](https://github.com/200166shang/ros-robot/issues/19)

## 环境与方法

- Orange Pi 3B，AArch64 Rockchip RK356x，ROS 2 Foxy。
- UVC 实体摄像头：Logitech `046d:0825`，设备为 `/dev/video0`，配置为 1280×720 MJPEG，请求帧率 30 FPS。
- 解码缩放比例为 0.5，输出为 640×360 `rgb8`，话题为 `/camera/image_raw`。
- 速率探针以 Best Effort QoS 订阅 `/image_raw/compressed` 和 `/camera/image_raw`。每轮先预热 8 秒，再测量 10 秒。采集和相机发布 FPS 取自 `usb_camera_node` 每 5 秒输出的统计值。启动等待和一次摄像头重开均不计入测量窗口。
- RViz2 通过现有 headless noVNC 服务加载 `img_decode/config/camera_preview.rviz`。预览将 RViz 渲染速率限制为 5 FPS，并使用 Best Effort 图像 QoS。测量速率时关闭了 GUI，因为软件渲染会降低开发板上的数据处理速率。

## 测量结果

| 构建配置 | 摄像头采集 | 相机话题发布 | 解码输出 | 说明 |
|---|---:|---:|---:|---|
| OpenCV | 29.8 FPS | 29.79 FPS | 27.69 FPS | 实体摄像头经 OpenCV 解码 JPEG；RViz2/noVNC 显示了实时图像。 |
| Rockchip MPP/RGA | 29.8 FPS | 29.79 FPS | 29.79 FPS | 实体摄像头经 MPP 解码、RGA 缩放；RViz2/noVNC 显示了实时图像。 |
| MPP/RGA，`frame_divider=2` | 29.8 FPS | 14.88 FPS | 14.88 FPS | 按配置，相机发布和解码速率约为采集速率的一半。 |

未设定固定 FPS 门槛，也未与 ROS 1 比较。相机节点启动时偶尔报告采集超时并重新打开 `/dev/video0`；测量在摄像头开始输出帧且预热结束后进行。

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
