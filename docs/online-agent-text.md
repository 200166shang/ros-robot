# 在线文本交互（#63）

ROS 2 Foxy / Python 3.8，使用 Python 标准库，不需要 OpenAI 或 DashScope SDK。
现有 `llm_ros_node`、`command_agent` 和本地 `res/fc` 桥接继续可用。
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

Ctrl+C 退出。节点先停止接入/发布再释放 ROS 资源；后台 HTTP 请求受连接与回合超时限制，无自动重试。超时动作不能安全取消，因此在途调用结束前新回合拒绝为 busy。

## Interface 与回复契约

`OnlineInteraction.submit(text)` 返回 `turn_id`、`status`、`reply`、`actions`；ROS 将同一对象 JSON 发布到 `/online_agent/result`。
状态为 completed/failed/rejected/busy；每项动作保留原顺序、名称、绑定参数及 simulated_success/real_success/failed/unknown/not_executed。
日志使用同一 turn_id 关联。未实现动作整表拒绝，不静默忽略。

provider 支持旧 `function/response` 与现有本地 `fc/res`，函数字符串可为 `head_nod` 或 `head_nod()`，参数只接受 Python 字面量，不使用 eval。
流式 JSON 片段先完整收集后解析一次；普通聊天目前完整回复输出，未新增逐字话题。动作回复由确认结果生成，不采用模型提前承诺，故混合聊天的自由文本不纳入动作结果回复。

设备 Adapter 用 `ActionRegistry.register(name, execute, validate)` 注册。execute 必须返回明确状态字典；validate 不得有副作用，整表执行前完成校验。未来 #64/#65 复用此 Interface，设备异常保守报告 unknown；明确失败回执报告 failed。
本票没有新增持久记忆、语音或真实设备控制。

## 检查与真实在线验收

```bash
PYTHONPATH="ros2_ws/src/robot_agent:$PYTHONPATH" python3 -m pytest -q ros2_ws/src/robot_agent/test
ruff check .
ruff format --check .
# 需要 ROS 环境、外部 Key 与配置，真实在线探针通过公开话题验证两轮
PYTHONPATH="ros2_ws/src/robot_agent:$PYTHONPATH" python3 ros2_ws/src/robot_agent/test/online_ros_probe.py \
  --ros-args -p config_file:="$HOME/.config/ros-robot/online.json"
```

Ruff 固定验证版本 0.9.10、目标 py38，仅覆盖在线迁移模块/探针和行为测试，不一次性重排旧 Python 代码。报告见 [验收记录](online-agent-text-validation.md)。

在线 SSE 与 JSON 输出依据阿里云官方文档：
[流式输出](https://www.alibabacloud.com/help/en/model-studio/stream)、
[结构化输出](https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output)。
