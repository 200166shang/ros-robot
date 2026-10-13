# robot_bringup

`tracking.launch.py` 启动基础跟踪系统的全部感知模块：Camera、Decoder、YOLO、YDLIDAR、平台 TF 和 ObjectTrack。系统只有一个启动组合；雷达融合与 Follow 在运行时通过 Service 分别控制。Launch 不会在节点退出后自动重启节点，也不会因单个节点退出而关闭整个组合。

## 启动

```bash
# 启动全部感知模块和默认开启的 Foxglove Bridge
ros2 launch robot_bringup tracking.launch.py

# 不启动 Foxglove Bridge
ros2 launch robot_bringup tracking.launch.py with_foxglove:=false
```

主入口只提供 `with_foxglove`（默认 `true`）。Camera、Decoder、YOLO、YDLIDAR、平台 TF 和 ObjectTrack 都会启动。LiDAR Fusion 默认关闭，Follow 默认 standby；`object_track/config/object_track.yaml` 中 `dry_run` 默认 `true`，因此控制命令只写预览日志，不发布 `/tracking/cmd_vel_safe`。

Launch 使用 ROS 2 的正常生命周期管理。节点退出不会自动重启，也不会触发其余节点退出；按 Ctrl-C 会正常关闭本次 Launch 启动的节点。

## 启用跟随

先确认雷达持续发布 `/scan`，并且 `camera <- laser_link` TF 已发布：

```bash
ros2 topic hz /scan
ros2 run tf2_ros tf2_echo camera laser_link
```

确认输入就绪后，依次启用 ObjectTrack 的 LiDAR Fusion 和 Follow：

```bash
ros2 service call /tracking/set_lidar_enabled std_srvs/srv/SetBool "{data: true}"
ros2 service call /tracking/set_enabled std_srvs/srv/SetBool "{data: true}"
```

关闭 Follow 会通过统一输出接口发送零速度。关闭 LiDAR Fusion 会销毁 ObjectTrack 的 `/scan` 订阅、清理投影和控制状态；如果 Follow 正在运行，也会将其置为 standby 并发送停止命令。此 Service 不会启动或停止 YDLIDAR 驱动。

Follow 只有在收到同步图像和检测、LiDAR Fusion 已启用、TF 可用且扫描未过期时才会启用。运行期间扫描过期时，ObjectTrack 输出零命令并清除旧距离，不会回退成仅按图像跟随。服务拒绝时会返回未就绪原因。

## 配置归属

硬件、Topic、模型和算法参数由对应 package YAML 持有。修改配置后重新构建并 source 工作区，使安装空间中的文件更新。

| 配置文件 | 负责内容 |
|---|---|
| `usb_camera/config/usb_camera.yaml` | 采集设备、图像 Topic、frame、分辨率、帧率与采集分频 |
| `img_decode/config/img_decode.yaml` | 压缩图像输入、解码输出、缩放比例与解码分频 |
| `rknn_yolov6/config/rknn_yolov6.yaml` | 模型路径、检测 Topic、阈值和推理选项 |
| `ydlidar/config/ydlidar.yaml` | 串口、扫描 frame、量程和驱动参数 |
| `robot_bringup/config/platform.yaml` | 相机/雷达 frame 与静态外参 |
| `object_track/config/object_track.yaml` | 输入输出 Topic、TF frame、dry-run、控制参数和扫描超时 |

`object_track.yaml` 中的 `camera_frame`/`laser_frame` 必须与 `platform.yaml` 的静态 TF frame 一致。模型权重保存在仓库外。相机采集分频与图像解码分频是独立设置。

独立调试时可启动单个 package Launch；这些入口不会替你组合其他模块：

```bash
ros2 launch usb_camera usb_camera.launch.py
ros2 launch img_decode img_decode.launch.py
ros2 launch rknn_yolov6 rknn_yolov6.launch.py
ros2 launch ydlidar ydlidar.launch.py
ros2 launch robot_bringup platform_tf.launch.py
ros2 launch object_track object_track.launch.py
```

ObjectTrack 独立运行时，需要外部提供相机检测、YDLIDAR 和平台 TF。其 Enable Service 与组合启动使用相同的就绪检查。

`person_tracking_demo.launch.py` 仍负责独立的 Agent、Web 和 Voice 演示组合；它复用基础跟踪入口，不改变基础系统的启动职责。
