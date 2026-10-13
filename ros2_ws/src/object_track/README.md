# object_track

`object_track.launch.py` 只启动 ObjectTrack 节点并加载本 package 的 `config/object_track.yaml`。基础系统建议使用 `robot_bringup tracking.launch.py`，该入口会组合相机、检测器、YDLIDAR 和平台 TF。

ObjectTrack 启动后默认处于 Follow standby，LiDAR Fusion 也默认关闭。启用顺序为先启用 LiDAR Fusion，再启用 Follow：

```bash
ros2 service call /tracking/set_lidar_enabled std_srvs/srv/SetBool "{data: true}"
ros2 service call /tracking/set_enabled std_srvs/srv/SetBool "{data: true}"
```

LiDAR Fusion Service 只控制节点是否订阅并使用 `/scan`，不会启动雷达驱动。Follow 启用前会检查同步图像/检测、TF、LiDAR Fusion 和新鲜扫描；运行期间扫描超时会输出零命令并清空过期距离，不会退回视觉跟随。关闭 Follow 或正在运行时关闭 LiDAR Fusion 都会发送零命令。

默认 `dry_run: true`，命令仅写预览日志，不会发布真实速度消息。算法、相机投影和超时参数应修改本 package 的 YAML；静态外参归 `robot_bringup/config/platform.yaml` 管理，frame 名称必须保持一致。
