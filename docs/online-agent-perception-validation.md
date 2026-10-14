# #65 感知 Interface 验收

2026-10-14（北京时间），基线 `1e2929f`，独立 worktree
`ros-robot-issue-65`，分支 `codex/issue-65-perception`。

## 已验证

- TDD 从交互输入观察回复、动作结果与设备事件：首次缺少感知模块失败，
  实现后通过；迟到融合及源 tracking-only 映射各先失败再修复通过。
- `PYTHONPATH=ros2_ws/src/robot_agent python3 -m pytest -q
  ros2_ws/src/robot_agent/test/test_online_perception.py`：11 passed。
- 加载 Foxy 后 `ROS_DOMAIN_ID=167` 运行
  `test_online_perception_ros.py`：2 passed。实际 ROS 传输，固定服务响应；
  覆盖 dry-run 参数拒绝、TF 拒绝、迟到融合、不补 Follow、不重试。
- 完整 Python 回归（tests、robot_agent、robot_voice、robot_bringup）：
  初轮49 passed；后续最终结果在下节记录。
- Ruff 0.9.10 `check .` 和 `format --check .`；Pyright 1.1.390 在线模块：
  通过。类型检查须加载 `/opt/ros/foxy/setup.bash` 才能解析 ROS 包。
- robot_agent、object_track、robot_bringup、ydlidar 源码外 colcon 构建成功。
  YDLIDAR SDK 1.2.7 的既有头文件产生初始化/未使用参数警告，无构建错误。

## 失败记录与验收限度

- 复用 `robot_bringup/scripts/tracking_control_acceptance_probe.py`，实际
  ObjectTrack 与平台 TF，图像/检测/扫描为探针样例。第一次到达 fusion 和
  Follow 成功服务回执，但等待 no-target preview 超时。tracker 日志出现
  近期扫描超时暂停，并稍后出现 no-target 零预览。第二次等待标注图像超时。
  第二次与回归曾使用相同 ROS domain，存在隔离不足；固定探针结果未计为通过。
- 真实在线第一次：固定 bringup 被旧 underlay 缺失
  `img_decode.launch.py` 阻塞；真实模型正确选择 `start_receiving_image`，
  turn `056aa82d81614ba4970dfd5a84645894` 返回 failed，原因是没有采集控制订阅。
  未把在线模型成功连接等同于感知验收通过，随后重建缺失依赖并复验。
- 状态查询是“本入口最后确认”，现有服务没有实时只读查询；启动时未知。
  相机话题无硬件确认，发布完成仅代表请求提交，回复明确区分。

构建、运行配置、凭证与原始日志全部在源码外；dry_run=true，缺失执行设备
仍模拟。没有调整 ObjectTrack 前提、算法、bringup 组合或引入第二进程管理器。

## 最终实机在线复验通过

重建源码外 usb_camera、img_decode、rknn_yolov6 后，在 `ROS_DOMAIN_ID=166`
加载 Foxy、既有 robot_interfaces underlay、本票 install 与持久 SDK 环境，运行：

```bash
ros2 launch robot_bringup tracking.launch.py with_foxglove:=false
python3 ros2_ws/src/robot_agent/test/online_perception_probe.py \
  --ros-args -p config_file:=/外部目录/config.json
```

实际固定组合：相机 `/dev/video0` MJPEG 1280×720，MPP/RGA decoder，外部
YOLOv6 RKNN 模型，YDLIDAR SDK 1.2.7、115200 baud、10 Hz，平台 TF 与
ObjectTrack dry_run=true。日志确认相机约23 fps、检测约6 fps、雷达正在扫描。
RKNN 既有 core-mask 日志提示当前平台无实现，但初始化及实际推理继续完成。
所有设备均使用真实节点与真实数据，本轮没有替换 provider 或传感器样例。

外部配置使用 qwen-plus，provider_timeout=60 秒、action_timeout=5 秒；
凭证由已有源码外凭证文件注入环境，仅本验收进程对在线端点绕过代理。

| 真实在线输入动作 | 结果 |
| --- | --- |
| start_receiving_image | completed；采集请求发布，无硬件状态确认 |
| enable_lidar | completed；LiDAR fusion enabled |
| start_following | completed；融合确认与 Follow enabled |
| following_status | completed；本入口最后确认 follow=true、fusion=true，非实时状态 |
| disable_lidar | completed；LiDAR fusion disabled，tracker 返回 standby |
| stop_camera_collection | completed；Follow standby 已确认、采集 false 请求已发布 |
| start_receiving_image | completed；采集 true 请求已发布 |

Follow 回合 `854ac6bf2c1f4c84a75828b9f0175669`，关闭融合回合
`3726b1042df4401faf238b3cab8e07af`。7轮均为真实在线模型→ROS Interface→
实际结果→中文回复，探针退出码0，订阅 `/tracking/cmd_vel_safe` 未收到 Twist。
验收后关闭本次 launch 创建的全部子节点，没有改动常驻环境或设备配置。

固定 ROS 验收探针第三次在独立 domain、无编译负载时仍在 no-target preview
等待处超时，日志记录扫描时效检查触发暂停。**该探针未通过**，不把成功的
实机在线链路或固定服务测试当作它通过；完整探针时效场景仍是验收未满足项。

## 最终检查与审查

- 加载 Foxy，`ROS_DOMAIN_ID=168`，PYTHONPATH 加入源码 robot_agent/robot_voice，
  `python3 -m pytest -q tests ros2_ws/src/robot_agent/test
  ros2_ws/src/robot_voice/test ros2_ws/src/robot_bringup/test`：**50 passed**。
- Ruff `check .`、`format --check .`、`git diff --check`：通过。
- Pyright 在线全部模块：**0 errors, 0 warnings**。
- 对固定基线 `1e2929f` 执行 code-review 双轴审查：Standards 初审1项阶段事实
  丢失、Spec 初审1项截止时间起计不一致；均新增公共交互回归并修复。
  执行层在启动线程前建立绝对期限，标准 ContextVar 按线程隔离并恢复上下文；
  各感知阶段与外层等待复用同一期限。失败回执保留已提交采集/已确认待机事实。
  复审 Standards **0 findings**，Spec **0 findings**。
- 源码外 `colcon test`（sequential，ROS_DOMAIN_ID=169）：robot_agent、
  robot_bringup、object_track、ydlidar、usb_camera、img_decode、rknn_yolov6
  共7包测试任务完成；`colcon test-result --verbose` 汇总 **28 tests，
  0 errors，0 failures，0 skipped**。robot_agent 的现有 setuptools 测试任务
  本身发现0项；其行为测试由上面的独立 pytest 50项回归实际执行，未遗漏。

## 同步主线 #64 后复验

2026-10-14（北京时间）将主线 `13ef19b`（#72，完整模拟能力 #64）合入本分支，
合并提交 `2bef1be`。提示词和清单冲突保留52项完整模拟契约，同时加入本票
真实感知映射；注册表保留主线能力状态与本票绝对动作期限，不覆盖彼此。

- 新增公共交互回归：同回合 volume_set→fusion→Follow→volume_status→完整
  停止，结果来源分别为模拟或真实确认，模拟状态字段仍正常返回。
- 完整 Python 回归 **70 passed**，Ruff check/format 与 Pyright **0 errors**；
  robot_agent 重新构建成功。7包 colcon 测试再次汇总 **28 tests，0 errors，
  0 failures，0 skipped**；robot_agent 行为测试仍由独立 pytest 实际执行。
- 首轮真实在线7项原感知指令通过；追加混合回合
  `228170de84574c089546c385ae8a847c` 在 fusion 刚开启、近期扫描尚未到达时
  被服务拒绝。已完成音量模拟事实保留，查询/停止均 not_executed，未重试。
  该轮失败保留在源码外 sync-online-first.log，没有计为混合验收通过。
- 探针随后补齐真实数据前提：fusion 开启成功后观察 `/scan` 的两帧真实
  扫描到达，再提交混合回合。运行时动作不增加等待重试或削弱跟随前提。
- 重新启动真实固定组合与在线模型，**9轮全部 completed**，探针退出码0。
  第9轮 `f4f0000de5e5422ca8ecaa3a22ff0777` 为
  volume_set(35)→start_following→volume_status→stop_following，依次返回
  simulated_success、real_success、simulated_success、real_success；
  音量查询 level=35，完整停止确认 Follow standby 与 fusion disabled。
  全轮保持 dry_run=true，未观察到 `/tracking/cmd_vel_safe` Twist 输出。

原固定 ROS 探针的时效未满足项保持原记录，本次没有重跑或声称解决该探针问题。

## 统一能力表注册重构复验

2026-10-14（北京时间），以 `14027e5` 为固定基线重构，代码提交 `56df5b3`。

感知按 #64 的契约返回 `Dict[str, ActionHandler]`，入口通过
`registry.register_many(perception_actions(perception))` 组装。移除感知流程的
`register()` 与注册表模块依赖；共享截止时间随 ActionHandler 放在
`online_action_contracts`，执行层设置并恢复上下文，感知流程读取同一期限。
15个动作名称、别名、参数、状态与执行步骤保持原契约。

- 单文件感知行为 **13 passed**；完整 Python 回归 **70 passed**。
- Ruff check/format、Pyright 在线全部模块 **0 errors, 0 warnings**；
  robot_agent 在源码外重新构建，以下实机验收使用最终安装版本。
- code-review 对 `git diff 14027e5...HEAD` 双轴审查：
  Standards **0 findings**；Spec **0 findings**。
- 真实 qwen-plus、固定硬件组合、实际相机/检测/雷达/TF/服务，
  在线探针 **9轮 completed，退出码0**，未观察到安全话题 Twist 输出。
  Follow 回合 `30ac9a6cdd3d4d52aa5ae47a6cb49faf` 实际确认 Follow enabled。
  混合回合 `4112b313c6134820a58c8412550bfed8` 依次执行 volume_set(35)、
  start_following、volume_status、stop_following；返回模拟/真实/模拟/真实
  成功，音量 level=35，最后确认 Follow standby 与 fusion disabled。

此次复验保持原扫描数据前提和 dry_run=true；结束后关闭本次启动的节点。
原固定 ROS 探针时效未满足项继续保留，未将本轮成功当作该项已解决。
