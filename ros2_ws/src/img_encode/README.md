# img_encode

`img_encode` subscribes to a ROS 2 `sensor_msgs/msg/Image` topic and publishes a JPEG `sensor_msgs/msg/CompressedImage`. It preserves the input header and publishes `format: jpeg`.

Defaults:

- Input: `/camera/image_raw`
- Output: `/camera/image_raw/compressed`
- JPEG quality: `80` (valid range 1–100)
- Supported input encodings: `rgb8`, `bgr8`, `rgba8`, `bgra8`, and `mono8`

## Build

The `IMG_ENCODE_BACKEND` CMake cache option selects `AUTO`, `OPENCV`, or `MPP`. `AUTO` selects MPP/RGA on AArch64 and OpenCV on other architectures.

```bash
cd ros2_ws
colcon build --packages-select img_encode
```

Choose the OpenCV backend explicitly with:

```bash
colcon build --packages-select img_encode --cmake-args -DIMG_ENCODE_BACKEND=OPENCV
```

The MPP backend requires the Rockchip MPP headers/library and RGA headers/library. It uses RGA for RGB-to-YUV420P conversion and MPP's JPEG `q_factor` setting for quality; quality 100 maps to MPP's maximum `q_factor` of 99. Build it with `-DIMG_ENCODE_BACKEND=MPP`.

## Design

The node and `JpegEncoder` share the ROS message handling and RGB normalization path. `JpegEncoder` delegates JPEG generation through a small internal backend interface; CMake compiles either the OpenCV adapter or the MPP/RGA adapter selected by `IMG_ENCODE_BACKEND`. Each adapter owns only its encoding-specific work and resources.

## Run

```bash
ros2 launch img_encode img_encode.launch.py
```

Override topics or quality with ROS parameters `input_topic`, `output_topic`, and `jpeg_quality`. The node uses a best-effort, depth-one image QoS to keep the latest frame flowing through the camera pipeline. Unsupported encodings, malformed image buffers, and per-frame backend errors are logged and skipped.
