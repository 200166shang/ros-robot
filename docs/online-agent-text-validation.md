# #63 在线文本主链路验收

日期：2026-10-14（北京时间）。基线 `f9929316dadee184c207858da1622f0655eb9878`，实施分支 `codex/issue-63-online-text`，独立 worktree。主 checkout 的未提交 GLOSSARY/ADR 未修改或纳入本票。

## 环境与配置

Orange Pi aarch64，ROS 2 Foxy，Python 3.8.10，Ruff 0.9.10，Pyright 1.1.390。
DashScope qwen-plus、北京兼容 HTTPS 端点、provider_timeout=60 秒、action_timeout=5 秒，dry_run=true。
用户提供的 CSV 仅在验收进程内解析 API Key 并注入环境。凭证和运行配置、colcon build/install/log、在线原始结果均存源码外；本报告只有脱敏行为证据。

## 行为与真实在线证据

- 初始 TDD 测试因 OnlineInteraction 模块不存在失败；实现后普通聊天、顺序重复及跨轮动作通过。
- 9 项新增公共 Interface 行为测试通过：整表动作/参数校验零执行、顺序与重复、跨回合、SSE 片段仅执行一次、明确失败停止、动作超时 unknown/后项 not_executed/忙拒绝、provider 超时、异常与非法回执、重复 JSON 键。
- 现有加新增 Python 完整回归：`source /opt/ros/foxy/setup.bash`，PYTHONPATH 在原 ROS 路径上追加 robot_agent/robot_voice，然后 `python3 -m pytest -q tests ros2_ws/src/robot_agent/test ros2_ws/src/robot_voice/test ros2_ws/src/robot_bringup/test`：47 passed。其中 robot_agent 单包 17 passed。
- 真实在线 Interface 两轮均 completed，聊天无动作；点头→微笑→点头三个结果均 simulated_success。
- ROS 真在线公开话题探针 `test/online_ros_probe.py`：两轮 completed。聊天 turn `d283d3c1a519476e8f88f9880d7436b4` 回复“你好，我是小沫，很高兴认识你。”；动作 turn `4f9bf3762c3a4dec8dbb0026f553fa48` 回复“head_nod：模拟成功；head_smile：模拟成功；head_nod：模拟成功。”，参数均为空，无物理运动。
- ROS 探针曾暴露回执发布后 worker 尚存活导致下一轮错误 busy；已将接入标识释放放在发布前，复验通过。
- `colcon build`（仅 robot_agent；build/install/log 路径为源码外）成功。
- 安装后的 `ros2 run robot_agent online_agent --ros-args -p config_file:=<外部配置>` 输出 ready、dry_run=true；发送 SIGINT 后退出码 0。启动检查等待 ready，而非假设固定启动时长。
- Ruff `check .` 与 `format --check .` 通过；`compileall` 通过。Pyright 对在线主模块及 ROS 入口做静态类型检查；已修正可选校验器和配置路径类型。

## 审查与限度

按 code-review 对固定基线执行两项独立审查：Standards 发现 1 项多阶段编号注释缺失，已补齐；Spec 未发现缺失、范围扩张或错误实现。人工检查中文 docstring、主调用链、语义空行与 Adapter 职责。

本票不验收完整设备模拟 #64、真实相机/融合/Follow #65、持久记忆 #66、在线语音/TTS #67、综合启动 #68。无参数表情以外动作明确整表拒绝，不报告成功。聊天允许流式，本票采用流式传输后完整回复发布。动作回复是已确认结果汇总，未使用模型提前生成的动作承诺或混合聊天文本。

已发出的动作超时无法证明未执行，故报告 unknown，停止后项、不重试，并在在途调用结束前拒绝新回合。未来真实设备 Adapter 必须有参数校验和明确回执，不能把排队接受当作动作完成。
