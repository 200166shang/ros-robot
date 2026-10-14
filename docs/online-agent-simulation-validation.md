# #64 完整模拟验收记录

日期：2026-10-14（北京时间）。基线 `1e2929f`，分支 `codex/issue-64-simulated-capabilities`，独立worktree。实施前两次fetch确认origin/main，无其他主线更新。原工作区的本地GLOSSARY/ADR及其他文件未纳入本票。

## 证据

- 导航、音乐、头部、音量/WiFi四个纵向TDD切片：新增公开交互入口测试均先因动作未注册而rejected；对应实现完成后逐项通过。
- 新模拟行为测试18项通过：52项源动作/别名全覆盖、默认参数、位置/关键字参数、LCD状态、完整导航姿态、同轮位置注册后导航、导航冲突/取消/重启/未知目标失败停止、音乐FIFO与重复/推荐/停止/会话过滤状态、音量饱和/静音、固定WiFi、头部轨迹重复、五个方向和五种情感、25种无效参数整表拒绝零修改、实例隔离。
- 全部Python回归 **54 passed**，命令：

```bash
source /opt/ros/foxy/setup.bash
PYTHONPATH="$PWD/ros2_ws/src/robot_agent:$PWD/ros2_ws/src/robot_voice:$PYTHONPATH" \
  python3 -m pytest -q tests ros2_ws/src/robot_agent/test \
  ros2_ws/src/robot_voice/test ros2_ws/src/robot_bringup/test
```

- Ruff 0.9.10 `check .` 和 `format --check .` 通过，新增online模块和test_online模块在现有配置范围内。Pyright 1.1.390对修改/新增在线模块和演示检查：0 errors、0 warnings；Python目标3.8，ROS导入路径为`/opt/ros/foxy/lib/python3.8/site-packages`。
- ROS 2 Foxy / Python 3.8.10 全新 `colcon build --packages-select robot_agent` 通过，build/install/log位于源码外 `~/.cache/ros-robot-issue-64/`。不需要构建无改动的硬件C++包。
- 源码与实际安装版本的 `python3 -m robot_agent.online_simulation_demo` 均通过，安装版本从`/tmp`执行。五轮结果为4 completed、1 failed（预期未知目标）；失败后head_smile为not_executed，启动/错误提示音为模拟。
- 安装版本使用真实ROS入口与话题，在独立ROS_DOMAIN_ID=164运行公开话题探针。只将云端provider替换为固定响应Adapter；16项代表动作经`/online_agent/text`输入、`/online_agent/result`返回，turn `2625c1b7907847d994604f97b94330a8`，completed、全部simulated_success。验证active导航、音乐队列切到稻香、音量静音、WiFi文档专用IP。`/cmd_vel`订阅没有收到消息，节点发布者仅result、parameter_events、rosout。探针、配置与原始结果留在源码外缓存。

## 设计和限制

人工检查：交互主链路保持整表校验、顺序执行、失败停止和确认后回复；data携带模拟快照，detail进入可信回复。状态分别集中在HeadSimulation、NavigationSimulation、MusicSimulation、VolumeSimulation；简单WiFi和提示音为函数，不建每动作类或通用框架。中文docstring、公共类型标注、语义空行与关键阶段编号已检查。

头部采用虚拟时间，修正源部分动作忽略duration的行为，姿态顺序与旧LCD映射保留；duration不对应真实等待或舵机驱动。完整契约和可独立运行步骤见 [模拟说明](online-agent-simulation.md)。模拟导航只确认目标活动，不确认到达。

本次真实云端模型复验 **未运行**：执行环境没有DASHSCOPE_API_KEY。固定provider的ROS验证不是云端证据，#63历史云端通过也不作为本版本复验。本票验收要求的固定响应全类别模拟已完成；真实感知#65、记忆#66、在线语音#67及综合云端/录音验收#68仍独立交付。

## Standards

0 findings。独立审查检查了中文文档、Interface类型、生命周期、输入校验、状态所有权和dry-run隔离，未发现可执行的规范违例或设计异味。

## Spec

0 findings。独立审查确认52项动作/别名、默认参数、状态、顺序/重复、失败停止和演示覆盖验收要求；云端未复验与凭证缺失明确记录，未发现范围扩张或错误行为。

审查固定点为`1e2929f93c2721675f912e74f4f33d0aca12af8f`，命令`git diff <固定点>...HEAD`。总计Standards 0项、Spec 0项，各轴均无待修复问题。
