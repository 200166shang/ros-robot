# rknn_yolov6

`rknn_yolov6` subscribes to RGB images and publishes detections plus an annotated image. It keeps the current ROS 2 interface used by the tracking pipeline:

- Input: `/camera/image_raw` (`sensor_msgs/msg/Image`, `rgb8`)
- Detections: `/ai_msg_det` (`robot_interfaces/msg/Dets`)
- Annotated image: `/camera/image_det` (`sensor_msgs/msg/Image`, `rgb8`)
- Enable control: `/enable_detector` (`std_msgs/msg/Bool`)

The detector retains separate inference and output stages with capacity-two drop-oldest queues. The AArch64 RKNN backend uses RGA for resize; the Haar backend is a host-side fallback for interface checks and face detection. Both use the same ROS messages.

## Build

`RKNN_YOLOV6_BACKEND` accepts `AUTO`, `RKNN`, or `HAAR`. `AUTO` selects RKNN on AArch64 and Haar on other architectures. The RKNN backend needs the installed RKNN runtime, RGA headers/library, and an official `rknn_api.h` header compatible with that runtime. The header is supplied from an external SDK include directory and is not stored in this repository. For the verified runtime 1.4.0, the official header is in [Rockchip's v1.4.0 runtime SDK](https://github.com/airockchip/rknpu2/blob/v1.4.0/runtime/RK356X/Linux/librknn_api/include/rknn_api.h).

On AArch64, build against the SDK header installed outside the source tree:

```bash
source /opt/ros/foxy/setup.bash
cd ~/code/ros-robot
colcon --log-base /tmp/ros-robot-rknn-log build \
  --base-paths ros2_ws/src --packages-up-to rknn_yolov6 \
  --build-base /tmp/ros-robot-rknn-build \
  --install-base /tmp/ros-robot-rknn-install \
  --cmake-args -DRKNN_YOLOV6_BACKEND=RKNN \
  -DRKNN_API_INCLUDE_DIR=/path/to/rknn/include
```

For a host build or to select Haar explicitly:

```bash
source /opt/ros/foxy/setup.bash
cd ~/code/ros-robot
colcon --log-base /tmp/ros-robot-haar-log build \
  --base-paths ros2_ws/src --packages-up-to rknn_yolov6 \
  --build-base /tmp/ros-robot-haar-build \
  --install-base /tmp/ros-robot-haar-install \
  --cmake-args -DRKNN_YOLOV6_BACKEND=HAAR
```

## Run

The launch file keeps the existing topic and parameter names. Model weights and Haar cascade data are external files. Set `model_path` for RKNN, or `haar_cascade_path` for Haar:

```bash
source /opt/ros/foxy/setup.bash
source /tmp/ros-robot-rknn-install/setup.bash
ros2 launch rknn_yolov6 rknn_yolov6.launch.py \
  model_path:=/path/to/yolov6.rknn
```

`labels_path` defaults to the package's `config/coco_labels.txt`. The runtime parameters are `input_topic`, `detections_topic`, `annotated_topic`, `confidence_threshold`, `nms_threshold`, `enabled`, `always_process`, `print_perf_detail`, and `use_multi_npu_core`. Confidence and NMS default to `0.30`; performance detail and multi-core use default to `false`.

To process files without a camera, enable `is_offline_image_mode`, set `offline_images_path` to an OpenCV glob pattern (for example `/data/images/*.jpg`), and set `offline_output_path` to an output directory. The node publishes the same detection and annotated-image messages and saves numbered `.jpg` files there. The output directory's parent must already exist.

## Test

The topic test publishes a synthetic `rgb8` image and checks the detection and annotated-image topics, including header and dimensions. It uses an external RKNN model and labels on AArch64, or an external Haar cascade for the fallback. The offline test also checks that an annotated file is saved. Supply a sample image with `RKNN_YOLOV6_TEST_IMAGE` to run that case.

For the RKNN build, set the paths to local assets before running the package test:

```bash
source /opt/ros/foxy/setup.bash
source /tmp/ros-robot-rknn-install/setup.bash
export RKNN_YOLOV6_TEST_MODEL=/path/to/yolov6.rknn
export RKNN_YOLOV6_TEST_LABELS="$PWD/ros2_ws/src/rknn_yolov6/config/coco_labels.txt"
export RKNN_YOLOV6_TEST_IMAGE=/path/to/test.jpg
cd /tmp/ros-robot-rknn-build/rknn_yolov6
ctest --output-on-failure
```

For Haar, set `RKNN_YOLOV6_TEST_CASCADE=/path/to/haarcascade_frontalface_default.xml` and run `ctest` from that backend's package build directory. The tests exercise the public ROS interface and do not enable tracking actuation.
