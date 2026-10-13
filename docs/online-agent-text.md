# ROS 2 Online Agent 文本入口（#55）

入口独立于现有 `llm_ros_node` 本地桥接。Online Agent 使用旧在线
`{"function":["volume_set(30)"],"response":"我会模拟设置音量。"}` 协议。
所有已实现设备动作均为模拟，结果包含 `simulated=true`。没有真实执行器话题、
PWM、系统音量或网络修改；Follow 保持现有 `dry_run=true`，本入口不启动 Follow。

## 构建及外部配置

在仓库根目录执行；需 ROS 2 Foxy、Python 3.8、colcon 和 pytest。
在线传输使用 Python 标准库 HTTPS，无需额外模型 SDK。

```bash
source /opt/ros/foxy/setup.bash
colcon build --base-paths ros2_ws/src/robot_agent \
  --build-base /tmp/ros-robot-55-build --install-base /tmp/ros-robot-55-install \
  --packages-select robot_agent
source /tmp/ros-robot-55-install/setup.bash
mkdir -p ~/.config/robot_agent
chmod 700 ~/.config/robot_agent
```

在源码目录之外创建 `~/.config/robot_agent/online.json`，设置权限 `chmod 600`：

```json
{
  "model": "qwen-plus",
  "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
  "timeout_seconds": 60,
  "api_key": ""
}
```

API key 填入这个外部文件，或通过 `DASHSCOPE_API_KEY` 环境变量提供。
必须使用自己账户所在地域/工作空间的 endpoint 与模型；配置路径必须是绝对路径，
不得位于 Git checkout 内。缺少凭证启动明确失败，不会降级成固定响应冒充在线运行。
[百炼结构化输出官方文档](https://www.alibabacloud.com/help/zh/model-studio/qwen-structured-output)。

## 启动、输入及观察

```bash
ros2 run robot_agent online_agent --ros-args \
  -p config_file:="$HOME/.config/robot_agent/online.json"
```

其他终端同样 source ROS 和 install 后，先订阅：

```bash
ros2 topic echo /online_agent/response
ros2 topic echo /online_agent/action_events
ros2 topic echo /online_agent/result
```

每个订阅命令使用一个终端。再发送：

```bash
ros2 topic pub --once /online_agent/user_input std_msgs/msg/String \
  "{data: '你好，请普通聊天，不执行动作。'}"
ros2 topic pub --once /online_agent/user_input std_msgs/msg/String \
  "{data: '请模拟将音量设置为30，调用 volume_set(30)。'}"
```

回复话题给出中文文本，动作事件与 result 为 JSON，包括实际 success、simulated、
参数执行结果或 error。失败动作不会采用模型的“已完成”宣称。未知或清单中未实现的
动作返回失败；不同动作并发，原始调用字符串完全相同时同轮去重，下一轮可再次执行。
同一节点的不同输入轮次串行处理，在线请求最多等待配置的 timeout_seconds。
发送前先启动节点和观察订阅；主题队列深度为10，快速大量输入不是持久任务队列。
Ctrl+C 停止节点；模拟状态随进程结束清除，本阶段不持久保存对话或记忆。

## 验证

```bash
PYTHONPATH=ros2_ws/src/robot_agent:$PYTHONPATH python3 -m pytest \
  ros2_ws/src/robot_agent/test -q
PYTHONPATH=ros2_ws/src/robot_agent:$PYTHONPATH python3 \
  ros2_ws/src/robot_agent/test/online_ros_probe.py
# 有真实凭证时，用同一 ROS 收发探针验证普通聊天及模拟动作：
PYTHONPATH=ros2_ws/src/robot_agent:$PYTHONPATH python3 \
  ros2_ws/src/robot_agent/test/online_ros_probe.py \
  --config "$HOME/.config/robot_agent/online.json"
```

不带 `--config` 的探针明确标记 `fixed_provider`，不能作为真实在线验收。
运行输出及凭证配置保存在源码之外；勿提交真实对话记录或密钥。
完整的60个源动作、参数、别名和后续映射见
[动作迁移清单](online-agent-action-inventory.md)。
语音、记忆、复杂头部队列和 ROS 感知服务迁移属于 #54 后续切片，本阶段未实现。
