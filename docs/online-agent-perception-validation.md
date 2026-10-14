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
