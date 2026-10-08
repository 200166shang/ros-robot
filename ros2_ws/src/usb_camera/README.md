# usb_camera 使用说明

`usb_camera` 包提供两个独立程序：`usb_camera_node` 用于向 ROS 发布相机图像，`camera_bench` 用于测量相机采集到 ROS 发布和接收的性能。

## 构建与加载

在仓库根目录执行：

```bash
cd ros2_ws
source /opt/ros/foxy/setup.bash
colcon build --packages-select usb_camera
source install/setup.bash
```

如果当前终端使用 Zsh，把上面两处 `setup.bash` 换成 `setup.zsh`。构建后每个新终端都需要重新加载 ROS 和工作区环境。

## 运行相机发布节点

```bash
ros2 launch usb_camera usb_camera.launch.py
```

默认从 `/dev/video0` 采集 1280×720、请求帧率 30 FPS 的 MJPEG 图像，并发布到 `/image_raw/compressed`。Launch 默认启用 `lazy`：没有图像订阅者时不会持续打开相机。可以在另一个终端运行下面的命令建立订阅并查看实际发布帧率：

```bash
ros2 topic hz /image_raw/compressed
```

## 运行相机性能基准

`camera_bench` 独立打开相机，在一个私有 ROS 话题上发布压缩图像并订阅自身，用于测量采集、发布和接收链路。测试时请停止其他直接打开同一相机设备的程序。

```bash
ros2 run usb_camera camera_bench --ros-args \
  -p device:=/dev/video0 \
  -p width:=640 \
  -p height:=480 \
  -p fps:=30 \
  -p duration_seconds:=3.0 \
  -p csv:=/tmp/camera_bench.csv
```

参数如下：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| `device` | `/dev/video0` | V4L2 相机设备路径 |
| `width` | `1280` | 请求图像宽度 |
| `height` | `720` | 请求图像高度 |
| `fps` | `30` | 请求帧率；设备实际输出帧率可能不同 |
| `duration_seconds` | `30.0` | 正式测量窗口，不包含首帧等待和预热时间 |
| `csv` | `camera_bench.csv` | CSV 报告路径；每次成功运行追加一行 |

运行阶段：先打开并配置相机，首帧最多等待 15 秒；取得首帧后预热 2 秒；然后按 `duration_seconds` 测量。正常完成后节点打印汇总并自动退出。失败的运行不会写入成功的 CSV 记录。

汇总包含实际分辨率、采集/发布/接收帧数和 FPS、V4L2 序号缺口、发布与接收总数差、平均发布到接收延迟，以及平均 JPEG 大小。FPS 按正式测量窗口计算，因此应以输出中的实际 FPS 为准，`fps` 参数只表示请求值。

例如，输出 `capture 45 (15.00 fps)` 表示设备在 3 秒测量窗口内交付了 45 帧；即使请求了 30 FPS，也不代表设备一定能达到该速率。

## 超时和设备检查

- 如果日志提示 15 秒内没有首帧，检查相机是否仍连接、设备路径是否正确，以及 USB/UVC 是否有重置记录：

  ```bash
  v4l2-ctl --list-devices
  v4l2-ctl --device=/dev/video0 --all
  dmesg --ctime | grep -Ei 'usb|uvc|video'
  ```

- 如果实际 FPS 低于请求值，先检查设备报告的格式、帧率和曝光设置；请求帧率不等于实测帧率。
- CSV 使用追加模式。需要单独保存一轮结果时，为 `csv` 指定新的文件路径。
