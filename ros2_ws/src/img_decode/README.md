# img_decode

`img_decode_node` subscribes to `sensor_msgs/msg/CompressedImage`, decodes JPEG frames, scales them, and publishes `rgb8` images. It preserves the input header and defaults to `/image_raw/compressed` → `/camera/image_raw`, scale `0.5`, and `frame_divider: 1`.

The frame divider counts every received compressed image and processes each Nth input. A value below 1 is treated as 1. Scale must be in `(0, 1]`. With `lazy: true` (the default), the compressed-image subscription is active only while the output has subscribers.

## Build

On non-Rockchip targets, `AUTO` selects OpenCV. On `aarch64`/`arm64`, `AUTO` selects Rockchip MPP/RGA and requires their development headers and libraries (typically `/usr/include/rockchip`, `/usr/include/rga`, `librockchip_mpp`, and `librga`). Select a backend explicitly with `IMG_DECODE_BACKEND=OPENCV` or `IMG_DECODE_BACKEND=ROCKCHIP`.

```bash
source /opt/ros/foxy/setup.bash
colcon build --packages-select img_decode --cmake-args -DIMG_DECODE_BACKEND=OPENCV
```

For the Rockchip path on the Orange Pi:

```bash
colcon build --packages-select img_decode --cmake-args -DIMG_DECODE_BACKEND=ROCKCHIP
```

`AUTO` is the default when `IMG_DECODE_BACKEND` is not specified. The startup log reports the selected backend.

## Run

```bash
source install/setup.bash
ros2 run img_decode img_decode_node
```

The `camera_decode.launch.py` launch file starts the camera and decoder together. Decoder parameters are `input_topic`, `output_topic`, `width`, `height`, `scale`, `frame_divider`, and `lazy`. `width` and `height` set the maximum decoded frame size used to provision the Rockchip output buffer; their defaults match the legacy 1280x720 camera stream and each must be in `[1, 8192]`.

## `img_decode`

`img_decode_node` 订阅 `sensor_msgs/msg/CompressedImage`，解码并缩放 JPEG，然后发布 `rgb8` 图像。输出保留输入 header，默认话题为 `/image_raw/compressed` → `/camera/image_raw`，缩放比例为 `0.5`，`frame_divider` 为 `1`。

divider 按收到的压缩图像计数，每 N 帧处理一帧；小于 1 的值按 1 处理。缩放比例范围为 `(0, 1]`。默认 `lazy: true`，只有输出话题有订阅者时才会订阅输入。

非 Rockchip 平台的 `AUTO` 默认选择 OpenCV；`aarch64`/`arm64` 默认选择 Rockchip MPP/RGA，需要安装对应开发头文件和库。可通过 CMake 参数 `IMG_DECODE_BACKEND=OPENCV` 或 `IMG_DECODE_BACKEND=ROCKCHIP` 显式选择，启动日志会显示当前后端。

参数包括 `input_topic`、`output_topic`、`width`、`height`、`scale`、`frame_divider` 和 `lazy`。`width` 与 `height` 用于配置 Rockchip 解码输出缓冲区，默认值沿用旧版 1280x720 相机画面，取值范围为 `[1, 8192]`；`camera_decode.launch.py` 会同时启动相机与解码节点。
