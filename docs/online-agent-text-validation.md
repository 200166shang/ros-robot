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

## 代码可读性重构复验

按用户的代码审美要求，`submit` 保留四步业务主线，模型解析、顺序执行及结果回复按职责集中；动作处理器、调用与已校验命令采用具名字段，取消执行器/校验器的索引约定。参数解析与业务校验分开，线程结果使用具名回执。

保留 register/execute、动作参数语法、默认参数、元组解包与相等比较及原错误状态。没有新增设备功能、每动作类或插件框架。同名 register 保持显式替换语义，配置阶段使用，不在处理回合时修改。

- Python 完整回归 **49 passed**；补充合法调用/default/literal 参数与非法展开/重复参数/属性调用的公共交互测试。
- Ruff check/format、Pyright 全部在线模块、robot_agent colcon build 通过。
- 真实 ROS 话题在线复验：聊天 turn `e4229516c939417190a86ce7f31f7842` completed；点头→微笑→点头 turn `cc73104713034b378ae802a5bf860c53` completed，三项仍为 simulated_success。
- 以重构前 `ac35276` 为固定点重新进行 code-review：Standards **0 findings**，Spec **0 findings**。

## 超时生命周期与执行事实修正

此前“动作调用线程退出后即可恢复接入”的规则由以下规则替代：模型超时调用结束后丢弃迟到输出；动作超时/异常/unknown 保留 Future 和原回合记录，只有显式 `reconcile(turn_id)` 核对明确成功或失败回执后解除 busy。未知或异常回执继续阻塞，须核实实际设备状态后重新启动入口。不取消、重试或补执行动作。

删除 Event、Queue、CallOutcome、OperationTimeout 的同步协议，改用标准 Future；回合锁只承担互斥，模型在途与动作待核对分别管理。统一 make_result 构造返回结构。模型、参数校验、执行与回复报告的异常各自处理，执行后的任何报告异常都保留动作记录。

- 修复前两项回归测试分别复现自动恢复接入和回复异常误报动作未执行；修复后通过。
- 公共 Interface 验证迟到成功、迟到失败、未知/异常持续阻塞、错 turn_id 拒绝、核对不补执行、已发布结果不被核对改写、报告故障保留完成项，以及迟到模型动作建议被丢弃。
- Python 完整回归 **55 passed**；Ruff、Pyright 与 robot_agent colcon build 通过。
- 首次真实 ROS 在线复验聊天回合失败、动作回合成功；未把首次运行报告为通过。重新运行后聊天 `4ad64c2bfcd94da88d92357d8c55effc` 和模拟动作 `91b507b96a2848c59eb9c3431cb3f8e6` 均 completed。对已完成回合经 `/online_agent/reconcile` 核对，返回同 turn_id 的 rejected，不重新执行。真实未知硬件回执未验收，本票仍只模拟硬件。
- 对固定点 `12f3410` 执行双轴审查：Standards 0 findings，Spec 0 findings。
