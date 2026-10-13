# Orange Pi 固定跟踪组合验收（2026-10-13）

关联：Issue #50、Spec #47、ADR 0005/0006。验证环境为当前 Orange Pi、ROS 2 Foxy、YDLIDAR SDK 1.2.7、RKNN runtime 1.4.0 / driver 0.9.6、RGA 1.9.3。全程 `dry_run: true`，没有底盘执行；`/tracking/cmd_vel_safe` 发布者数为 0。

## 真实板端结果

| 项目 | 实际观察 |
|---|---|
| 持久 SDK 和硬件程序 | 薄包装成功启动 Camera、Decoder、Detector、YDLIDAR、平台 TF、ObjectTrack 六个进程；没有缺失共享库或可执行文件。SDK 重启后加载由操作者在 #48 确认。 |
| 相机与检测 | `/dev/video0` MJPEG 1280×720，经 MPP 解码后进行 RKNN 推理。模型输入为 640×352；输出检测坐标和图像保持原始 1280×720，不把模型尺寸当作原图坐标。 |
| RGA | 原先真实 ROS 图像引发 `RGA_MMU unsupported memory larger than 4G` 和 resize 错误；改用持久 DMA32 源/目标缓冲后，分进程 10 帧探针及整套真实相机运行未再出现该 resize 错误。 |
| 雷达与 TF | F2 串口扫描正常；Tracker 日志确认 `loaded transform camera <- laser_link`。一个 15 秒观察窗口收到 91 帧 `/scan`，末帧 255 个采样、144 个有效量程。 |
| 投影与距离 | 真实 `/camera/image_det_track` 中，绿色扫描点沿画面中部横向分布；选中的检测框曾显示约 0.10 m 的距离估计。此帧模型把沙发上物体误识别为 person，证明真实扫描的投影和距离计算，不证明真人识别或距离精度。投影仍沿用平台外参与相机参数，未进行标定精度验收。 |
| 服务顺序 | 同步输入存在但 Fusion 关闭时，Follow 返回 `success=false`、`enable LiDAR fusion first`。Fusion 开启后返回成功；新鲜扫描到达后 Follow 返回成功。 |
| Fusion 关闭 | Follow 开启期间关闭 Fusion，日志产生 `linear.x=0.000 angular.z=0.000; not published`，随后 `tracking standby because LiDAR fusion was disabled`；再次开启 Follow 被拒绝。 |
| 扫描停止且同步图像停止 | 对本次 Detector 与 YDLIDAR 子进程发 SIGINT，其他四个进程继续运行；没有新的同步检测输入时，独立定时器仍记录 `tracking waiting for LiDAR range` 的两个零速度。 |
| 生命周期 | 上述两个子进程没有重启，也未结束其他节点。随后退出 Launch，剩余四个自建进程全部清理；单独启动的 ROSBridge（PID 57161）仍监听 9090，没有被组合接管。 |
| 观察连接 | 使用现有 ROSBridge 9090，WebSocket 探针订阅真实 `/scan`，开启 Fusion/Follow 后关闭连接并重连。扫描时间戳从 `1791878017.652763000` 更新到 `1791878036.453596000`；断开期间 dry-run 预览持续，重连没有新的 Follow 状态切换。 |

实际命令：

```bash
./scripts/run-tracking.sh with_foxglove:=false
# 另一个已加载 ROS 环境的终端，单独拥有观察桥接进程：
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
ros2 service call /tracking/set_lidar_enabled std_srvs/srv/SetBool "{data: true}"
ros2 service call /tracking/set_enabled std_srvs/srv/SetBool "{data: true}"
```

## 受控输入与构建证据

- 硬件组合串行构建成功（10 个 package）；最终 ObjectTrack 合并版本再次构建成功。默认并行首次构建曾因内存不足被杀，操作指南改为串行构建。
- `test_tracking_launch.py`：3 passed；检查固定组合和可选 Bridge 参数。
- RKNN Topic 集成测试：1280×720 输入通过，保留原图坐标和 header；另一个发布进程逐帧验证 10 个不同时间戳的检测和图像输出。
- ObjectTrack `ctest`：2/2 passed，包含平台旋转矩阵三射线投影回归。
- `object_track_acceptance_probe.py`：PASS。覆盖精确时间同步、最大 person、目标切换后的距离重算、无目标零输出、恢复、限幅、扫描过期且图像不更新、无有效目标量程时两个速度归零、TF 晚于启动超时后通过 Fusion 服务恢复。
- `tracking_control_acceptance_probe.py`：PASS。隔离环境使用平台 TF 和独立 10 Hz 扫描流，覆盖服务、观察订阅断开、Fusion 扫描订阅生命周期。持续扫描模拟真实驱动，不修改节点超时参数。
- 在真实大图多路网页订阅与隔离探针同时运行时，重复探针曾因同步输入接收超时失败；隔离测试和实际网页运行分开验证，不把此失败算作通过。上表接收计数属于观察端收到的数据，不是发布端性能基准。

## 本次修复依据

1. 普通虚拟内存的实际物理页可能超出板上 RGA 的 32 位 DMA 寻址范围。使用 `system-uncached-dma32` 堆，并由局部资源对象持有 fd、映射和 RGA handle；失败明确报告，没有 CPU 降级。
2. Foxy 的 `getRPY()` 在平台 `pitch=-π/2` 时丢失旋转，扫描投影退化为中心射线。直接传递 TF 旋转矩阵，保留 `R*p+t` 的完整坐标变换。
3. 每帧按当前目标重新筛选新鲜投影点；没有有效目标量程时，线速度和角速度均为零，不使用旧值或 `range_max`。
4. 启动 TF 等待结束后，Fusion 服务重新查询实际 TF，允许操作者在独立模块启动就绪后重试。

## 验证边界与操作者确认

- 操作者明确要求跳过两个人的真实最大目标选择、人工离开/返回场景；相应算法行为由受控公开接口探针验证，未声称完成这些物理场景。
- 当前 Foxy 未安装 `foxglove_bridge`。操作者确认使用已有 ROSBridge；真实观察断连/重连通过该协议完成。`with_foxglove:=true` 的包分支由 Launch 测试检查，本板没有执行原生 Foxglove Bridge 启动。
- 已安装 ROSBridge 对同一话题混用网页的 `cbor-raw` 和 JSON 订阅会报转换错误；观察探针与网页统一使用 `cbor-raw` 后通过。此环境问题没有通过修改跟踪逻辑掩盖。
- RKNN runtime 仍打印本板不支持 `rknn_set_core_mask` 的诊断；推理实际正常。报告中的“resize 错误消失”不表示所有外部库诊断都消失。
- 模型权重、官方 SDK 头文件、截图、录制和构建产物未提交。板上详细日志保留于 `/tmp/issue50-*`，包括 `board-current.log`、`current-projection.json`、`rosbridge-observation.json` 以及各 RED/GREEN 探针记录；临时文件不会保证跨重启保存，本报告保留可复核的结果与限制。
