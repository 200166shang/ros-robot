# 完整 Online Agent：统一启动与操作

ROS 2 Foxy / Python 3.8，统一入口组合真实在线 ASR、LLM、TTS、
完整动作注册表、会话记忆与真实感知 Adapter。文本和录音使用同一个
`online_voice_agent`，不要同时启动 `online_agent` 或另一份语音入口。
LCD、舵机、底盘、导航、音乐、系统音量、WiFi 与提示音均保持日志模拟。
`dry_run=true`；Follow 的设备参数、安全路由、TF 和数据前提继续生效。

## 准备依赖与外部资源

硬件准备按[跟踪操作指南](../ros2_ws/src/robot_bringup/README.md)，包括
MPP/RGA、RKNN runtime、源码外官方 SDK 头、RKNN 模型和 YDLIDAR SDK。
不沿用旧 ROS 1 的硬编码启动路径，不修改 PWM 权限，不访问舵机驱动。
运行依赖为 ROS 2 的 rclpy、std_msgs、std_srvs、rcl_interfaces，
以及 Python `websocket-client>=1.6,<2`。无需 DashScope/OpenAI SDK。

以下命令均为 Bash，从本 checkout 根目录执行。首次安装 Python 依赖到
源码外目录，让 Foxy 继续使用系统 Python 3.8；不要切换到不同版本的
Python 来启动 ROS。

```bash
python3 -m pip install --target "$HOME/.local/lib/ros-robot-online" \
  'websocket-client>=1.6,<2'
export PYTHONPATH="$HOME/.local/lib/ros-robot-online${PYTHONPATH:+:$PYTHONPATH}"
source /opt/ros/foxy/setup.bash
source scripts/ydlidar-sdk-env.zsh
export ONLINE_BUILD_ROOT="$HOME/local-data/ros-robot/online-build"
colcon --log-base "$ONLINE_BUILD_ROOT/log" build --base-paths ros2_ws/src \
  --build-base "$ONLINE_BUILD_ROOT/build" \
  --install-base "$ONLINE_BUILD_ROOT/install" \
  --packages-up-to robot_bringup robot_voice --executor sequential \
  --cmake-args -DRKNN_API_INCLUDE_DIR="$HOME/sdk/rknn/include"
source "$ONLINE_BUILD_ROOT/install/setup.bash"
```

模型位置由 rknn_yolov6 包配置指定；部署到其他板子时调整该包配置，
不要把模型或 SDK 头复制进源码。构建目录与运行数据均放在源码外。
退出终端后需重新加载 ROS、SDK、Python 依赖及该 install 环境。

## 外部配置与凭证

创建 `$HOME/.config/ros-robot/online.json`（源码外），将下面两个数据路径
替换为自己的绝对路径。自定义 prompt 可用 `system_prompt_file`，默认
使用安装包内完整旧人设/动作目录及部署约束，不依赖运行目录。

```json
{
  "dry_run": true,
  "model": "qwen-plus",
  "api_key_env": "DASHSCOPE_API_KEY",
  "provider_timeout": 60,
  "action_timeout": 5,
  "speech_timeout": 60,
  "asr_model": "paraformer-realtime-v2",
  "asr_attempts": 2,
  "tts_model": "cosyvoice-v2",
  "tts_voice": "longfeifei_v2",
  "tts_attempts": 3,
  "tts_failure_threshold": 5,
  "tts_retry_delay": 1,
  "silence_timeout": 120,
  "output_dir": "/absolute/external/online-results",
  "memory_file": "/absolute/external/conversation-summary.json",
  "memory_recent_turns": 6,
  "memory_summary_trigger": 6,
  "microphone_enabled": false,
  "playback_enabled": false
}
```

凭证只通过环境变量传入，不填 `api_key`，不写到源码、日志或命令参数。
Bash 交互读入（不会回显或进入 shell 历史）：

```bash
read -rs -p 'DashScope API Key: ' DASHSCOPE_API_KEY
printf '\n'
export DASHSCOPE_API_KEY
```

模型、端点与 Key 地域授权必须匹配。端点配置见[文本说明](online-agent-text.md)
和[语音说明](online-agent-voice.md)。本板代理曾导致 WSS 任务启动事件超时；
允许直连时仅对该终端设置，其他网络按实际路由配置：

```bash
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}dashscope.aliyuncs.com"
export no_proxy="$NO_PROXY"
```

## 一次启动完整组合

```bash
ros2 launch robot_bringup online_agent.launch.py \
  config_file:="$HOME/.config/ros-robot/online.json"
```

启动相机、解码、检测、雷达、平台 TF、ObjectTrack 及一个完整在线入口。
融合默认关闭、Follow 默认 standby；启动不等于启用跟随。可视化默认关闭，
安装 Foxglove Bridge 后可加 `with_foxglove:=true`。全部进程由正常 ROS
Launch 生命周期管理，没有第二进程管理器或自动重启策略。

另一终端加载相同 ROS/install 环境，先监听结果，再发输入：

```bash
ros2 topic echo /online_agent/result std_msgs/msg/String
# 在第三个终端输入：
ros2 topic pub --once /online_agent/text std_msgs/msg/String \
  '{data: "请依次点头、微笑、再点头"}'
ros2 topic pub --once /online_agent/wav std_msgs/msg/String \
  '{data: "/absolute/path/to/existing.wav"}'
```

WAV 须为非空 PCM16、单声道、16kHz；直接录音不要求唤醒词。实际识别文本
在 `transcript` 中，不能以文件名作为识别证据。LLM 与 TTS 均实际在线。
每回合 JSON/WAV 在 `output_dir`，以 `turn_id` 关联，回复只依据动作回执。
`real_success` 的相机结果仅确认控制请求已发布，不确认硬件开关；查询会
明确未知。fusion/Follow 则需要真实服务确认。状态查询是本入口最后确认，
不能当作外部控制后的实时设备状态。

开启融合后，观察真实 `/scan` 与 `/camera/image_det` 数据到达，再请求
Follow。若前提未满足，失败即停止余下动作，不自动重试，也不削弱前提。
详情见[感知操作](online-agent-perception.md)。

独立单 WAV CLI 只用于在线语音/模拟设备诊断，不接入 ROS 感知：

```bash
ros2 run robot_agent online_voice_wav \
  --config "$HOME/.config/ros-robot/online.json" \
  --wav /absolute/path/to/existing.wav
```

### 可选麦克风与播放

需安装 `arecord`/`aplay`（alsa-utils）。外部配置设
`microphone_enabled=true`，按需要指定 `record_executable`、
`record_device`（默认 default）、`record_seconds`（默认8）；
`playback_enabled=true` 及 `play_executable`、`play_device` 可启用回复播放。
麦克风按半双工录制→识别→动作→合成/播放→恢复采集。
麦克风识别需要“小沫小沫”或五种同音唤醒，随后连续对话；明确休眠或
静音120秒回 standby。录音/文本直接回合绕过该会话门控。
音乐只模拟，但麦克风会话仍依原音乐控制关键词过滤。

### 记忆、恢复与退出

```bash
ros2 topic pub --once /online_agent/clear_memory std_msgs/msg/String \
  '{data: "clear"}'
ros2 topic pub --once /online_agent/tts_enable std_msgs/msg/String \
  '{data: "enable"}'
ros2 topic pub --once /online_agent/reconcile std_msgs/msg/String \
  '{data: "原动作回合turn_id"}'
```

清空影响本配置的近期上下文与持久摘要；忙时拒绝。摘要达到配置阈值后
保存，重启同一配置加载摘要。详见[记忆说明](online-agent-memory.md)。
TTS 连续失败后降级文本，显式 enable 恢复；不重复模型或动作。
动作在途/未知时保持 busy，reconcile 核对迟到回执，不补执行余下动作。
仍未知需操作者核实设备状态，不能仅以线程退出解除安全互斥。

启动终端 Ctrl+C 退出本次 Launch 创建的全部进程。在线入口关闭语音连接，
取消/回收录制与播放子进程，等待有界在线调用后释放 ROS。凭证、录音、
TTS音频、记忆、模型、SDK头和构建输出不提交。

## 可复现综合验收

统一启动运行中，用真实录音执行探针；不传入固定模型或传感器替身：

```bash
python3 ros2_ws/src/robot_agent/test/online_integration_probe.py \
  --wav /absolute/path/to/existing.wav \
  --evidence-dir "$HOME/local-data/ros-robot/online-acceptance"
```

探针读取实际 dry_run 参数，验证真实图像/扫描、在线相机控制、fusion、
Follow、模拟/真实混合顺序、有意重复、WAV全链路，以及零运动消息/发布者。
使用专用验收配置（memory_summary_trigger=2），避免干扰日常记忆。
停止并重新启动同一 Launch/配置，再加 `--recall` 验证摘要召回与清空。
该阶段会清空专用记忆。失败记录仍保存，断言失败不能计为通过。

覆盖核对见[源业务清单](online-agent-inventory.md)，实际命令、结果、版本
与限度见[#68验收报告](online-agent-integration-validation.md)。
固定响应回归用于验证确定性失败/恢复语义，不能替代真实在线验收。


对于实际包含人物跟踪请求的既有录音，可另用 `--recording-only` 验证
录音识别后确实发出真实感知动作。探针先确认fusion并观察扫描，再提交
WAV，要求实际ASR文本非空且Follow动作有真实确认，最后停止跟随：

```bash
python3 ros2_ws/src/robot_agent/test/online_integration_probe.py \
  --recording-only --wav /absolute/path/to/existing-tracking-request.wav \
  --evidence-dir "$HOME/local-data/ros-robot/online-acceptance"
```

文件名不参与识别或动作选择；只有服务端ASR/模型/设备结果满足条件才通过。
