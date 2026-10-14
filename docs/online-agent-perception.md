# Online Agent 感知控制

#65 在 Online Agent 注册已有相机采集、Follow 和 LiDAR fusion Interface。
保持 `dry_run=true`；不启动子进程、不向底盘话题发布运动、不改变固定 bringup。

## 启动

先按既有流程构建并启动固定组合：

```bash
ros2 launch robot_bringup tracking.launch.py with_foxglove:=false
ros2 run robot_agent online_agent --ros-args -p config_file:=/外部目录/config.json
```

ROS 环境、SDK 和模型配置沿用各包说明。外部在线配置及凭证加载见
[在线文本入口](online-agent-text.md)。Agent 不自动启动或重启设备。

## 动作与结果

所有下列动作无参数，沿用整个动作列表先校验、顺序执行、失败停止规则。

| 动作 | 实际语义 |
| --- | --- |
| `start_receiving_image`、`start_camera` | 向 `/enable_camera` 发布 true 恢复采集 |
| `stop_camera_collection`、`stop_camera` | 先确认 Follow standby，再发布 false 暂停采集 |
| `query_camera_status` | 明确报告采集状态未知；现有话题没有状态回执 |
| `start_following`、`start_tracking` | 恢复采集请求→确认 fusion→确认 Follow |
| `stop_following` | 先确认 Follow standby，再确认关闭 fusion |
| `enable_tracking`、`disable_tracking` | 仅 `/tracking/set_enabled`，不自动切换 fusion |
| `toggle_following` | 按本入口最后确认切换；启动后状态未知时拒绝猜测 |
| `following_status`、`query_person_tracking_status` | 报告本入口最后确认的 Follow/fusion，初始为未知 |
| `enable_lidar`、`disable_lidar` | `/tracking/set_lidar_enabled`；控制 tracker 扫描订阅 |

相机发布完成的 `real_success` **仅表示采集请求提交成功**，回复和动作 detail
明确写明没有设备确认，不能推断采集已恢复、预览/检测状态或相机硬件开关。
没有相机话题订阅端时报告 failed；查询不会猜测状态或改变设备。

Follow/fusion 必须消费实际 `SetBool.success/message`；服务不可用或拒绝报告
failed，保留原因。启用前读取 `/object_track/get_parameters` 的实际 `dry_run`，
只有 bool true 才发启用请求。TF、同步图像/检测、LiDAR 发布端、近期扫描的
检查继续由 ObjectTrack 执行。关闭 fusion 的成功回执也确认 Follow 已待机。

这些服务没有只读实时状态 Interface；状态回复明确标记“本入口最后确认”，
不是设备实时状态。外部网页控制、tracker 重启可能改变状态；需要确定行为时
明确启动或停止，不依赖历史快照推断。相机语义不是网页预览订阅控制。

多阶段动作共享截止时间。超时只报告 unknown，保留调用，不取消或重试。
迟到融合/安全参数回执不能继续提交 Follow；迟到待机回执不能继续暂停相机。
通过 `/online_agent/reconcile` 显式核对，后续动作不会补执行。完整参数与
回合语义见[在线文本入口](online-agent-text.md)。

## 验收

固定模型事件从 `OnlineInteraction.submit` 观察回复、动作回执与顺序。
`test_online_perception_ros.py` 在隔离 ROS domain 内通过真实 ROS 传输与固定
设备响应测试安全参数、拒绝、超时与迟到回执；这不是实机或在线模型证据。

真实在线探针只连接已启动组合，不管理设备；凭证由环境提供：

```bash
python3 ros2_ws/src/robot_agent/test/online_perception_probe.py \
  --ros-args -p config_file:=/外部目录/config.json
```

探针依次恢复采集、开启融合、开启 Follow、查询、关闭融合、暂停并恢复采集，
检查真实在线模型选出的函数、实际回执以及无 Twist 输出。环境阻塞时探针失败，
不能用固定 provider 或传感器样例替代实机通过。详情见[验收报告](online-agent-perception-validation.md)。
