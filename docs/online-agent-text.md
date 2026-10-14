# 在线文本交互（#63）

ROS 2 Foxy / Python 3.8，使用 Python 标准库，不需要 OpenAI 或 DashScope SDK。
用户已确认弃用本地桥接。robot_agent 仅保留 Online Agent；本地模型节点、客户端、校验器和专用探针均已移除。模型输出解析仍接受 `fc/res`，这仅是响应契约兼容，不再提供本地桥接进程。

网页相机/Follow 控制由 web_video_server 的 tracking_control 入口独立提供，使用 /web/control 和 /web/control_result；它不调用模型，也不是 Online Agent 的真实设备 Adapter（#65）。
本入口保持 `dry_run=true`，只模拟 head_nod/head_smile/head_shake，无硬件输出。
完整迁移范围、参数和后续票见 [动作与业务清单](online-agent-inventory.md)。

## 外部配置与启动

凭证放在环境变量（不要输入 shell 历史，不要放进仓库），非敏感配置另存源码外，例如 `$HOME/.config/ros-robot/online.json`：

```json
{
  "model": "qwen-plus",
  "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
  "api_key_env": "DASHSCOPE_API_KEY",
  "provider_timeout": 60.0,
  "action_timeout": 5.0
}
```

默认 system prompt 保存在包内 `robot_agent/online_system_prompt.txt`，随安装包发布，通过 Python 3.8 的 importlib.resources 读取，不依赖启动目录。
它完整保留旧 `LLMAgent.agent_sys_prompt` 的人设、格式要求、示例和动作目录，末尾添加当前部署约束，避免把未实现动作或模拟动作当成真实成功。会话记忆的摘要任务由记忆职责构造，配置及清空见 [在线会话记忆](online-agent-memory.md)。

需要自定义时，在外部配置中添加 `"system_prompt_file": "/absolute/path/prompt.txt"`。文件为 UTF-8，启动时读取一次；指定文件为空或不存在则启动失败，不静默回退。自定义文件负责保留 JSON 契约，实际执行仍受动作注册表限制。

若本机 HTTPS 代理出现间歇性超时、且网络允许直连北京端点，可只对 DashScope 域名绕过代理。启动节点前在该终端设置（不修改全局代理配置）：

```bash
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}dashscope.aliyuncs.com"
export no_proxy="$NO_PROXY"
```

已验证安装版本在此设置下完成真实在线聊天、顺序模拟动作与 ROS 回执。使用其他 endpoint 时替换成对应主机名；需要代理的环境保持自身路由配置。

端点/模型需要匹配 Key 地域与授权；不会输出 Key 或 HTTP 错误正文。`api_key` 明文字段禁止使用。
provider_timeout/action_timeout 单位秒，必须是正有限数。网络和模型访问失败返回失败回合，不能用模拟 provider 冒充真实通过。

```bash
source /opt/ros/foxy/setup.bash
read -rs 'DASHSCOPE_API_KEY?API Key: '; echo
export DASHSCOPE_API_KEY
cd ros2_ws
colcon build --packages-select robot_agent
source install/setup.bash
ros2 run robot_agent online_agent --ros-args \
  -p config_file:="$HOME/.config/ros-robot/online.json" -p dry_run:=true
```

上面 `read` 是 zsh 语法；bash 使用 `read -rs -p 'API Key: ' DASHSCOPE_API_KEY`。
另一终端先监听结果，再提交文本：

```bash
source /opt/ros/foxy/setup.bash
ros2 topic echo /online_agent/result std_msgs/msg/String
ros2 topic pub --once /online_agent/text std_msgs/msg/String '{data: "你好，请只聊天"}'
ros2 topic pub --once /online_agent/text std_msgs/msg/String '{data: "请依次点头、微笑、再点头"}'
```

Ctrl+C 退出。节点先停止接入/发布再释放 ROS 资源；后台 HTTP 请求受连接与回合超时限制，无自动重试。超时动作不能安全取消，线程退出后也不自动解除 busy。模型超时只保留在途 Future，结束后可接入新回合。

动作超时、异常或回执 unknown 后，按原 turn_id 显式核对迟到回执：

```bash
ros2 topic pub --once /online_agent/reconcile std_msgs/msg/String '{data: "原动作回合的turn_id"}'
```

结果仍发布到 `/online_agent/result`，关联原 turn_id。调用未结束时保持 unknown；迟到回执明确成功或失败后解除 busy，后续未执行项不补执行。迟到回执仍未知或异常则继续阻塞，需要操作者核实设备实际状态后重新启动入口，不能以线程退出代替设备确认。
已发布的超时记录是快照，核对生成新的回执，不改写旧记录。

## Interface 与回复契约

`OnlineInteraction.submit(text)` 返回 `turn_id`、`status`、`reply`、`actions`；ROS 将同一对象 JSON 发布到 `/online_agent/result`。
状态为 completed/failed/rejected/busy；每项动作保留原顺序、名称、绑定参数及 simulated_success/real_success/failed/unknown/not_executed。
日志使用同一 turn_id 关联。未实现动作整表拒绝，不静默忽略。

provider 支持旧 `function/response` 与现有本地 `fc/res`，函数字符串可为 `head_nod` 或 `head_nod()`，参数只接受 Python 字面量，不使用 eval。
流式 JSON 片段先完整收集后解析一次；普通聊天目前完整回复输出，未新增逐字话题。动作回复由确认结果生成，不采用模型提前承诺，故混合聊天的自由文本不纳入动作结果回复。

动作模块分为三个职责：`parse_action` 只把函数字符串解析为位置/关键字参数；注册表按设备签名和参数含义完成全表校验；设备回执只在执行出口检查一次。
`ActionHandler.execute/validate` 明确表达设备契约，`ActionCommand.name/parameters` 明确表达已绑定动作。ActionCommand 保留原返回元组的解包和相等比较兼容性。
`submit` 集中展示收齐模型回复、全表校验、顺序执行和确认回复，I/O 隔离只用标准 Future 交还结果；回合互斥、模型在途与动作待核对分别管理，保留不可取消语义。

设备 Adapter 用 `ActionRegistry.register(name, execute, validate)` 注册，配置阶段可显式替换同名契约，处理回合时不修改注册表。execute 必须返回明确状态字典；validate 不得有副作用，整表执行前完成校验。未来 #64/#65 复用此 Interface，设备异常保守报告 unknown 并保持待核对；明确失败回执报告 failed。Adapter 必须按设备实际完成状态返回，排队接受不能作为成功。配置的 action_timeout 仅限制主链路等待，不取消已提交操作。
持久摘要与有限近期上下文见 [在线会话记忆](online-agent-memory.md)；语音和真实设备控制由后续票实现。

## 检查与真实在线验收

```bash
PYTHONPATH="ros2_ws/src/robot_agent:$PYTHONPATH" python3 -m pytest -q ros2_ws/src/robot_agent/test
ruff check .
ruff format --check .
# 需要 ROS 环境、外部 Key 与配置，真实在线探针通过公开话题验证两轮
PYTHONPATH="ros2_ws/src/robot_agent:$PYTHONPATH" python3 ros2_ws/src/robot_agent/test/online_ros_probe.py \
  --ros-args -p config_file:="$HOME/.config/ros-robot/online.json"
```

Ruff 固定验证版本 0.9.10、目标 py38，启用 E/W/F/I，代码79列、注释/docstring72列，仅覆盖在线迁移模块/探针和行为测试，不一次性重排旧 Python 代码。报告见 [验收记录](online-agent-text-validation.md) 和 [PEP 8 审查](online-agent-pep8-review.md)。

在线 SSE 与 JSON 输出依据阿里云官方文档：
[流式输出](https://www.alibabacloud.com/help/en/model-studio/stream)、
[结构化输出](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output)。


## Tracking/web demo after local bridge retirement

`./scripts/run-demo.sh` now delegates directly to the standard ROS launch;
it no longer starts llama-server or local model weights. The default starts
tracking and web controls. To include Online Agent, pass:

```bash
./scripts/run-demo.sh with_online_agent:=true \
  online_config_file:="$HOME/.config/ros-robot/online.json"
```

Credentials must already be in the environment. Local ASR/TTS can be launched
separately using robot_voice; the retired local-LLM voice acceptance probe is
removed. Fresh builds are required: an incremental install can leave obsolete
executables behind after their source entry points are removed.
