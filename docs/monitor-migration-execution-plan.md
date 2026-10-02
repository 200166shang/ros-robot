# Monitor ROS 1 → ROS 2 执行方案

## 目标

把 `/home/orangepi/code/robot/src/monitor` 的系统和进程监控能力迁移到当前 ROS 2 Foxy 工作区。监控节点、注册客户端和验证探针均使用 C++；ROS 消息与服务保留在独立的 `monitor_interfaces` 包中。保持 ROS 1 的 3 秒采样周期和 rosbag 记录行为，并采用 Foxy 当前安装的 rosbag2 C++ API。

本方案已在 `feature/monitor` 实施。下方执行记录列出已完成的实现与验证结果。

## 已确认的行为约定

| 项目 | 执行决定 |
| --- | --- |
| ROS 版本 | ROS 2 Foxy，按板端安装的 Foxy API 构建 |
| 采样周期 | 3 秒，对应 ROS 1 `ros::Rate(1.0 / 3.0)` |
| 输出话题 | 默认 `/monitor_info`，恢复 `monitor_topic` 参数 |
| rosbag | 在 monitor 节点内使用 `rosbag2_cpp` C++ API 记录 `/monitor_info` |
| rosbag URI | 恢复 `bag_file_path` 参数；ROS 2 中把它作为 bag URI/目录路径，默认值保留为 `monitor_data.bag` |
| 存储插件 | Foxy 默认 SQLite3，显式使用 `storage_id = "sqlite3"` |
| 负载均值字段 | 保留 `load_avg_1`、`load_avg_5`、`load_avg_15`；`load_avg_5` 表达 Linux 5 分钟负载，接口变更符合意图 |
| 客户端语言 | 仅提供 C++ 客户端；业务模块迁移到 C++ 后使用 `monitor_client` |
| 中文注释 | 在进程身份、CPU 计数、客户端租约和 rosbag 序列化等核心逻辑处添加简短中文说明 |

旧节点在有订阅者时发布消息，但每次采样都会写 bag。迁移时保持这个顺序和行为：采样一次，按订阅者数量决定是否发布，但始终写入 bag。

## 包与文件调整

### 1. `monitor_interfaces`

保留 `monitor_interfaces`，它是 ROS 2 消息和服务的语言中立定义，不是 Python 模块。

- 保留 `MonitorInfo`、CPU、内存、网络、节点监控消息及注册/注销服务。
- 保留 `CpuLoad.msg` 的 `load_avg_5` 字段。
- 保留注册服务中的 PID、进程启动时间和 registration ID。这些字段用于区分 PID 复用和同一进程中的多个 ROS 节点。
- 不把接口消息移回 `monitor` 包。

### 2. `monitor`

保留 C++ 系统采集和进程监控。按职责将 bag 写入从 ROS 节点编排逻辑中分开：

- 在 `MonitorNode` 中声明 `monitor_topic` 和 `bag_file_path` 参数。
- 新增 `MonitorBagWriter`（例如 `include/monitor/monitor_bag_writer.h` 与 `src/monitor/monitor_bag_writer.cpp`），只负责打开、写入和释放 rosbag2 writer。
- `MonitorNode::Sample()` 负责组织采样结果、条件发布、写 bag；维持清晰的执行顺序，并在采样流程的关键阶段间留空行。
- 采样周期改为 `std::chrono::seconds(3)`。
- bag 初始化失败时按旧行为让节点启动失败；单次写入失败时记录错误并让后续采样继续。
- 调整 `CMakeLists.txt`：删除当前不存在的 `launch`、`config` 安装路径；删除 Python `scripts` 安装项；加入 rosbag2 C++ 依赖。
- 移除未被当前采集器使用的 `ReadFile`、`Utils`；移除所有空实现的 `Stop()` 接口和覆写，避免保留无效扩展点。

Foxy 的 `rosbag2_cpp::writers::SequentialWriter` 使用 `open(StorageOptions, ConverterOptions)`、`create_topic(TopicMetadata)` 和序列化消息写入。写入 `MonitorInfo` 的执行步骤：

1. 用 `StorageOptions` 设置 bag URI 与 SQLite3 storage ID。
2. 用 `ConverterOptions` 设置输入、输出序列化格式为当前 RMW 的 CDR 格式。
3. 创建 `/monitor_info` topic metadata，类型名为 `monitor_interfaces/msg/MonitorInfo`。
4. 用 `rclcpp::Serialization<MonitorInfo>` 序列化采样消息。
5. 将数据和采样消息时间戳封装为 Foxy 要求的 `rosbag2_storage::SerializedBagMessage`，交给 writer 写入。
6. 用自定义 deleter 调用 `rcutils_uint8_array_fini` 释放序列化缓冲区；节点销毁前释放 writer，完成 bag 收尾。

Foxy 的 `rosbag2_cpp` 接口和序列化路径应以当前安装头文件为准；不要照搬较新 ROS 2 发行版提供的 typed `Writer::write(message, topic, time)` 便利接口。ROS 2 官方 Foxy C++ bag 教程可作参考：[Recording a bag from your own node (C++)](https://docs.ros.org/en/foxy/Tutorials/Advanced/Recording-A-Bag-From-Your-Own-Node-CPP.html)。

### 3. `monitor_client`

保留 C++ 注册客户端，作为其他 C++ ROS 节点的统一入口。

- 保留基于节点完全限定名、PID、进程启动时间和 registration ID 的注册方式。
- 保留周期续租和退出时注销，要求业务节点在 `rclcpp::shutdown()` 前调用关闭流程。
- 将 `MonitorRegistration` 定位为可嵌入已有 executor 的公共 RAII 客户端，使用 PImpl 隐藏续租、服务客户端和线程细节；补充简短的 C++ 用法说明。
- 注册客户端不接管业务节点的 `main()`、executor 或进程信号；应用在 ROS context 关闭前调用 `close()`。
- 在接口注释中明确 `close()` 可重复调用，以及析构/关闭需要发生在 ROS context shutdown 之前。
- 将 `multi_node_probe.cpp` 留作 C++ 端到端验证工具；不把一般用途的 `cpp_pubsub` 示例包作为 monitor 的运行依赖。

### 4. 移除 Python 和无关示例

从 monitor feature 提交中移除：

- 整个 `monitor_client_py` 包，包括 `lifecycle.py`、`setup.py`、`package.xml` 和 ament resource marker。
- `monitor/scripts/monitor_acceptance_probe.py`、`monitor_stability_probe.py`、`perception_perf_probe.py`。前两个的主路径检查由 C++ 探针覆盖；感知性能探针不属于 monitor 核心功能。
- `cpp_pubsub` 通用示例包。监控客户端验证由 `monitor_client` 自带的 C++ 探针承担。

当前 feature 中没有 Python 业务节点依赖需要同步更改。原工作区 stash 中的 Python 节点接入属于后续业务模块迁移工作；这些节点改成 C++ 后，直接使用 `monitor_client`，不为过渡阶段保留 Python 客户端。

## 核心计算与可读性调整

1. **修正 CPU 统计分母**：依据 `/proc/stat` 字段含义计算总 ticks；`guest`、`guest_nice` 已包含在 `user`、`nice` 中，不得在分母再次相加。
2. **使采样测试适配硬件**：不再假设设备固定有 4 个 CPU 核；通过读取 CPU 列表或验证总 CPU 项及每项有效值来断言。
3. **补齐关键逻辑注释**：只在读者需要理解系统约定的位置加短中文注释，不逐行复述代码：
   - `/proc/<pid>/stat` 中进程名可含空格和括号，以及字段索引如何对应 CPU 时间和启动时间。
   - PID 加进程启动时间用于抵御 PID 复用；registration ID 用于隔离节点实例。
   - CPU guest ticks 的包含关系，以及负载率分子、分母的选择。
   - 客户端定期续租、注销必须早于 ROS shutdown 的原因。
   - rosbag2 缓冲区所有权与释放方式。
4. **整理排版**：CMake 和 XML 每项依赖/安装目标独占一行；头文件按系统、ROS、项目分组；相关成员、方法和采样阶段聚合放置；逻辑段落间留空行。避免对无关业务包做格式化。
5. **明确指标单位**：为消息字段或相邻文档标明内存 GiB/MiB、网络 KiB/s、磁盘 KiB/s、CPU 百分比和累计 CPU 秒，避免消费者猜测。

## 执行步骤

### 阶段 A：收敛范围和配置

1. 确认上述接口字段与服务身份参数保持不变。
2. 将 ROS 1 `monitor_topic`、`bag_file_path` 参数迁移为 ROS 2 参数，设置同名默认值。
3. 确认 bag 默认 URI 不存在时可创建；若 URI 已存在或不可写，启动报错信息需包含 URI。
4. 从 CMake/package manifest 声明 Foxy 需要的 `rosbag2_cpp`、`rosbag2_storage`、`rcutils` 依赖；`rclcpp` 提供消息序列化 API。

### 阶段 B：修正监控实现

1. 先修正 CPU guest tick 分母和 CPU 数量硬编码测试。
2. 添加 `MonitorBagWriter`，使用 Foxy `SequentialWriter` API 实现单话题记录。
3. 在 `MonitorNode` 中恢复 ROS 1 参数名，设置 3 秒 timer，并按约定发布和写 bag。
4. 确保打开 bag 失败时启动失败；写入单条消息失败时记录错误但不停止监控。
5. 清理无用工具、空 `Stop()`、不存在的安装路径和 Python 安装项。
6. 移除 `monitor_client_py`、Python 探针和 `cpp_pubsub` 示例；为 C++ 客户端补简短用法说明。
7. 在进程身份、CPU 计数、客户端生命周期、bag 序列化处加入短中文注释，并整理相关文件格式。

### 阶段 C：验证主路径

**构建和单元测试：**

```bash
source /opt/ros/foxy/setup.bash
cd /home/orangepi/code/ros-robot/ros2_ws

colcon build --packages-up-to monitor monitor_client
colcon test --packages-select monitor monitor_client
colcon test-result --verbose
```

**运行时检查：**

1. 删除本轮测试使用的旧 bag URI，然后启动 `monitor_node`。
2. 验证节点启动后发布 `/monitor_info`，采样间隔约 3 秒；至少包含 CPU、内存和网络数据。
3. 使用 `ros2 topic echo --once /monitor_info` 检查消息时间戳、`load_avg_1/5/15`、非零内存总量及有限数值。
4. 运行 `monitor_client` 的 C++ 多节点探针。确认同一 PID 下两个节点分别出现；关闭一个客户端后只移除对应节点；关闭另一个后节点列表清空。
   - 启动命令为 `ros2 run monitor monitor_node`；另一个终端运行 `ros2 run monitor_client multi_node_probe`。
5. 先让 C++ 多节点探针正常退出并确认注册列表清空；再对 monitor 发 `Ctrl+C`，确认 bag writer 正常收尾。
6. monitor 退出后运行 `ros2 bag info <bag_uri>`，确认包含 `/monitor_info`、类型为 `monitor_interfaces/msg/MonitorInfo`，且消息数与采样时长相符；另确认 bag URI 不可写时节点明确启动失败。

## 完成标准

- monitor 运行时代码、客户端和随包验证代码均为 C++；`monitor_interfaces` 保持 ROS 语言中立定义。
- 构建、安装、单元测试通过，CMake 不再引用不存在的目录或未声明的依赖。
- 系统采样周期为 3 秒；`/monitor_info` 同时发布并记录到 Foxy rosbag2。
- bag 可通过 `ros2 bag info` 识别话题、类型和消息数量。
- CPU 统计不重复计算 guest ticks；测试不依赖特定 CPU 核数。
- C++ 客户端能独立注册、续租、注销；同进程多个节点互不覆盖。
- 核心逻辑的中文注释短且解释原因/约定；代码按逻辑分组，空行能区分独立步骤。

## 本次不做

- 不把 stash 中的 Python 业务模块迁移到 C++；它们等业务模块替换时再接入 C++ 客户端。
- 不做长时间稳定性压测、全量感知性能评估或 UI/可视化工作。
- 不把负载字段名恢复为 `load_avg_3`；当前 `load_avg_5` 对应实际 5 分钟负载。

## 执行记录（2026-10-01）

- 已将 monitor 运行时代码、客户端和验证探针收敛为 C++；移除 `monitor_client_py`、Python 探针、`cpp_pubsub`、未使用的 `ReadFile`/`Utils` 和空 `Stop()` 接口。
- 客户端已重构为 `monitor_client::MonitorRegistration`，公开头文件采用 PImpl；移除了未被调用的 `run_node()`、信号处理和 `registration_id()` 接口。
- 已新增 `MonitorBagWriter`，使用 Foxy `SequentialWriter` + `rclcpp::Serialization`；默认每 3 秒采样，恢复 `monitor_topic` 和 `bag_file_path` 参数。
- 已修正 CPU ticks 总量排除 guest 重复计数，并移除固定 CPU 核数的测试断言。
- 已加入 monitor 指标单位说明、C++ 生命周期用法和核心逻辑中文注释。
- `colcon build --packages-up-to monitor monitor_client` 通过；`colcon test --packages-select monitor monitor_client` 与 `colcon test-result --verbose` 通过，共 8 项测试。
- 实际启动 monitor 后，`ros2 topic echo /monitor_info` 收到系统采样消息；消息含 1/5/15 分钟 load average、CPU、内存和网络数据。
- `multi_node_probe` 输出 `reported_pids_match=1` 和 `result=PASS`，确认同一 PID 的两个节点可独立注册和注销。
- `ros2 bag info` 确认 SQLite3 bag 中包含 `/monitor_info`，类型为 `monitor_interfaces/msg/MonitorInfo`，并记录了多条消息。
- 将 bag URI 指向不可写的 `/proc/monitor_must_fail.bag` 时，节点启动失败，错误信息包含该 URI。
