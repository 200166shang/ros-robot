# 阶段 E/F：Nav2 导航、AMCL 与在线 SLAM 实施记录

日期：2026-09-25

仓库分支：`feature/robot-simulation-phases-c-f`

适用边界：Orange Pi 3B 上 ROS 2 Foxy/Qwen Agent；Mac 上独立 ARM64 Colima VM、ROS 2 Jazzy/Nav2 与浏览器。

当前证据等级：软件在环/跨设备集成原型，不是实体底盘验收或生产安全认证。

## 这次完成了什么

1. 在 Mac 的独立 Colima `ros-nav2` profile 运行 ARM64 Jazzy/Nav2 loopback，隔离于默认 Docker/Colima 环境。可选 `ideal`、`amcl`、`slam` 三种地图/定位配置；其中本次端到端主线实际使用在线 SLAM。
2. 新增固定地点 HTTP 网关。它只接受 `goal_a`、`goal_b` 等 allowlist 地点 ID，不接收任意坐标；有地图时还会检查目标是否在已知 free space 中。
3. Orange Pi Foxy Agent 通过 HTTP 客户端连接 Mac 网关，绕开 Foxy 与 Jazzy 的 DDS 互操作问题。Agent 暴露导航状态并能查询/取消任务；导航能力需在显式 `--navigation-sim` profile 打开，默认仍关闭。
4. 新增 Mac `scripts/open-nav-sim.sh`，在一条 SSH 会话中提供两个 loopback-only 转发：Mac `18081 → Orange Pi 8080` 聊天页面，以及 Orange Pi `127.0.0.1:18092 → Mac 127.0.0.1:18091` Nav2 API。脚本只建隧道，不启动或停止两端服务。
5. 修复 SLAM 的初始扫描/TF 时序竞争，并将 SLAM Toolbox 的 lifecycle manager bond watchdog 设为仿真专用关闭值；生命周期 configure/activate 仍执行，健康检查依赖地图、初始位姿变换和导航 Action 就绪状态。这个设置不是实体机器人建议值。
6. 网页画布根据在线地图版本重绘，标出仿真 profile；SLAM 的远处目标只有在探索扫描覆盖并确认可通行后才显示。

## 架构与安全边界

```text
Mac 浏览器 (18091) ──渲染地图/轨迹──> Mac Nav2 HTTP gateway
                                             │ localhost reverse SSH :18092
Orange Pi Qwen → ROS Agent ──固定地点 ID───┘
       Foxy                                  Jazzy + loopback + Nav2
```

- 板端不会安装 Jazzy/Nav2，也不把两套 ROS DDS 网络桥接起来。
- 导航 API 只绑定本机回环地址，经 SSH 隧道按需访问；不应把端口改成 `0.0.0.0`。
- 机器人运动发生在 Mac Colima 容器内；Agent 发送的是被允许的地点标识，不会向 Orange Pi 真实底盘发布 `/cmd_vel`。
- 没有启动板端 C270、RKNN/NPU、麦克风或硬件驱动。
- SLAM profile 用 loopback 的虚拟扫描生成器在私有 sandbox 世界中采样；Nav2/SLAM 消费生成的 scan 并产生估计地图，不能把仿真真值地图误称为算法地图。
- Loopback 是理想运动学模型，无质量/惯性、摩擦、碰撞、打滑、电机、编码器误差和真实雷达噪声。

## 本次实测结果

### 编译与静态检查

- Mac ARM64 容器镜像成功构建，镜像大小约 `986,679,015` bytes；容器能启动并通过 `/healthz`。
- Orange Pi 工作区正确在 `ros2_ws` 目录构建：`robot_agent` 与 `robot_bringup` 及依赖构建成功，用时约 14.7 秒。第一次错误地在仓库根目录运行 colcon 只生成了空构建元数据，随后仅删除了那次命令生成的 `build/ install/ log/` 三个精确路径，再从正确工作区完成构建。
- 项目根目录测试：25 项通过，1 项因系统 `sh` 支持 `pipefail` 而跳过。
- `robot_agent` Python 单元测试：16 项通过。
- touched Python 文件语法编译、Shell `bash -n` 与 `git diff --check` 均通过。

### SLAM 数据与导航 API

- 新启 SLAM profile 初始健康检查通过，但只识别了机器人起点；目标 A/B 仍未出现在可导航地点列表。板端 preflight 因此明确报出缺少目标，而不是启动后静默失败。
- 仅在 Mac 的隔离仿真容器中，以 `0.15 m/s` 虚拟速度行驶约 8 秒并停车；估计地图扩大到约 420 个更新版本，随后 `goal_a`、`goal_b` 出现在符合可通行条件的地点列表。
- scan 检查：`frame=base_scan`，240 beams，其中约 225 个有限读数，距离约 0.427–4.65m。
- Nav2 HTTP 任务测试：`goal_a` 最终 `succeeded`（约 4 秒，末端位置到目标约 0.26m）；另一任务通过 cancel API 最终 `canceled`。

### Orange Pi Agent 与真实 Qwen 请求

- Orange Pi `./scripts/run-demo.sh --check-only --navigation-sim` preflight 通过：模型/工作区/ROS、Mac API 反向隧道、目标地点均就绪。
- 使用 `./scripts/run-demo.sh --navigation-sim` 启动板端 Qwen、ROS Agent、网页。自然语言请求“请让虚拟机器人前往目标A，只使用已经启用的导航仿真功能。”经 Qwen 生成允许的 `navigate_to_goal_a` 调用，Agent 提交任务。回复明确区分“已提交”与“已到达”；之后 Mac Nav2 页面/API 显示任务成功。
- 单次观测：模型推理约 `17,173 ms`，完整网页回合约 `17,334 ms`。样本量为 1，不可称为平均值、P95 或性能 benchmark。
- ROS Python acceptance probe 直接验证 goal B 可提交、取消、状态进入 `canceled`。
- 收尾后 Orange Pi 上本次启动的 Qwen、Agent、Web 进程和端口均已退出；SSH 隧道也已关闭。

## 复现步骤：每个命令在哪运行

### 1. Mac：启动独立 Nav2/SLAM 服务

使用含本分支代码的 Mac 仓库 checkout：

```bash
cd /path/to/ros-robot
colima start ros-nav2 --cpus 2 --memory 4 --disk 30 --arch aarch64 --vm-type vz --activate=false
cd simulation/nav2-jazzy
export APT_HTTP_PROXY=http://192.168.5.2:7890  # 仅当当前网络需该代理
./scripts/nav2-up.sh slam                   # 或 ideal / amcl
```

查看 Nav2/地图 readiness：

```bash
curl --noproxy '*' -fsS http://127.0.0.1:18091/healthz
curl --noproxy '*' -fsS http://127.0.0.1:18091/api/v1/navigation/locations
```

如果刚启动 SLAM 时地点列表只有起点，这是预期：在线 SLAM 只建机器人实际看到的区域。地图还没有覆盖远目标时，不能导航到尚未观测的未知空间。

### 2. Mac：给隔离 SLAM 世界做一次确定性预热

仅用于当前 sandbox 样例；必须先确认没有正在执行的导航任务。这段速度命令只送入 Mac Colima 容器，不是 Orange Pi 命令：

```bash
docker --context colima-ros-nav2 exec ros-robot-nav2-loopback bash -lc '
  source /opt/ros/jazzy/setup.bash
  timeout 8s ros2 topic pub --rate 10 /cmd_vel geometry_msgs/msg/Twist \
    "{linear: {x: 0.15}}" >/dev/null 2>&1
  ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{}" >/dev/null 2>&1
'
curl --noproxy '*' -fsS http://127.0.0.1:18091/api/v1/navigation/locations
```

### 3. Mac：建立聊天与 Nav2 双向 SSH 隧道

```bash
cd /path/to/ros-robot
./scripts/open-nav-sim.sh
```

保持终端运行。脚本会打开 Mac 地图页 `http://127.0.0.1:18091/`；板端聊天网页未启动时会提示，但不影响先建好 Nav2 反向隧道。之后可通过 `http://127.0.0.1:18081/` 使用聊天页。按 `Ctrl-C` 只关闭此隧道。

若提示本地 18081 被占用，先用 `lsof -nP -iTCP:18081 -sTCP:LISTEN` 查清楚监听者；不要猜 PID 结束进程。可以等已有隧道释放，或通过 `DEMO_LOCAL_WEB_PORT` 选择未占用的本地端口。Mac Nav2 服务仍需在 18091，因为这是本实验配置的固定反向隧道目标。

### 4. Orange Pi：先做无副作用检查，再启动功能

```bash
cd /home/orangepi/code/ros-robot
./scripts/run-demo.sh --check-only --navigation-sim
./scripts/run-demo.sh --navigation-sim
```

第一个命令只检查模型、工作区、ROS、HTTP 反向隧道与当前可导航地点，不启动服务；第二个启动 Qwen + Agent + Web，不启动相机/NPU/麦克风/真实驱动。浏览器聊天 URL 在 Mac；Nav2 地图与机器人轨迹在 Mac 的 `18091` 页面。

发送前往目标 A/B 的自然语言请求后，应分别观察：聊天回合显示任务已提交、网页任务 ID/状态更新、Nav2 地图上的虚拟机器人运动与最终状态。取消任务可调用已映射的取消能力，再在 Nav2 UI/API 核对 `canceled`，不要只凭聊天文案判定。

## 关闭顺序

1. Orange Pi 的 `run-demo.sh --navigation-sim` 终端按 `Ctrl-C`，确认它只清理本脚本启动的进程。
2. Mac 的 `open-nav-sim.sh` 终端按 `Ctrl-C`，结束本脚本创建的 SSH 隧道。
3. Mac 停止本实验容器和独立 VM：

```bash
cd /path/to/ros-robot/simulation/nav2-jazzy
./scripts/nav2-down.sh
colima stop ros-nav2
```

不要用 `colima delete`，它会删除该 profile 及其已缓存数据；这次只需要停止释放资源。

## 仍未完成/不要夸大的结论

- 浏览器 UI/API 的 HTTP 端到端检查通过，但本次没有成功取得 Codex 桌面浏览器截图，页面仍需用户现场目视确认布局与动画体验。
- 本次没有在 Orange Pi 安装或运行 Nav2；Agent 是跨机器提交 HTTP 任务，不代表板端执行导航算法。
- SLAM 虚拟世界是已知 sandbox 通过射线生成虚拟测量，Nav2 使用虚拟 scan 在线建图；不是陌生真实房间的建图试验。
- 不包含刚体物理/碰撞/惯性/动态障碍、真实驱动响应、相机/NPU或真实激光雷达。Gazebo/Harmonic 保留为只有在这些验证需求出现时才做的扩展。
- 一次 17.3 秒 Qwen 回合只能作为现场记录，不能用于模型、网络或线程优化决策。后续若需要 benchmark，应固定 prompt 和地点，至少多次运行并报告中位数、P95、失败率，同时记录模型冷/热状态、板端 CPU/RAM/温度和 UI 观察开销。

## 代码与资料

- 仿真说明：[Nav2 Jazzy loopback README](../simulation/nav2-jazzy/README.md)
- 总体路线：[机器人能力迁移与仿真路线图](robot-capability-simulation-roadmap.md)
- 安全网关：`simulation/nav2-jazzy/ros2_ws/src/robot_nav2_gateway/`
- 板端客户端/开关：`ros2_ws/src/robot_agent/robot_agent/navigation_client.py`、`command_agent.py`、`llm_ros_node.py`
- 启动组合：`ros2_ws/src/robot_bringup/launch/navigation_sim_demo.launch.py`
- Mac 隧道：`scripts/open-nav-sim.sh`
