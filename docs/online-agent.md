# 完整 Online Agent：统一启动与操作

ROS 2 Foxy / Python 3.8，统一入口组合真实在线 ASR、LLM、TTS、
完整动作注册表、会话记忆与真实感知 Adapter。正常运行只有麦克风
`online_voice_agent`；文本/WAV由独立测试进程使用同一交互Implementation。
LCD、舵机、底盘、导航、音乐、系统音量、WiFi 与提示音均保持日志模拟。
Agent不配置dry_run；ObjectTrack自身仍dry_run=true，服务保留数据/TF前提。

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
  "record_device": "plughw:2,0",
  "record_seconds": 8,
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

正常入口自动录制麦克风，不能向它发布text/WAV/transcript或文本控制命令。
另一终端仅观察结果：

```bash
ros2 topic echo /online_agent/result std_msgs/msg/String
```

说“小沫小沫”后连续请求，明确“晚安”或静音120秒回待机。每轮录音默认
8秒，识别、动作和合成/播放结束后才开始下一轮；日志提示采集窗口。
音频/ASR/模型规则见[麦克风说明](online-agent-voice.md)。

每轮JSON/WAV在output_dir，以turn_id关联，回复只依据动作确认。
相机real_success只确认请求已发布，查询明确未知；fusion/Follow由服务
确认，状态查询表示本入口最后确认。融合开启后应另行观察真实扫描和检测
到达，再请求Follow；失败停止余下动作，不自动重试或弱化前提。
详情见[感知说明](online-agent-perception.md)。

独立单 WAV CLI 只用于在线语音/模拟设备诊断，不接入 ROS 感知：

```bash
ros2 run robot_agent online_voice_wav \
  --config "$HOME/.config/ros-robot/online.json" \
  --wav /absolute/path/to/existing.wav
```

### 可选麦克风与播放

需安装arecord/aplay（alsa-utils）；麦克风始终是正常入口唯一输入。
arecord -l核对record_device，配置record_executable、record_device与
record_seconds。playback_enabled=true及play_executable/play_device
可开启回复播放。缺失LCD、导航、舵机等仍保持明确模拟实现。

### 记忆、恢复与退出

正常入口没有clear_memory/tts_enable/reconcile文本话题。公共Interface
由同一调用者轮间调用，独立文本验收支持clear_memory/reconcile；退出后
可清理专用记忆文件。模型仍在途、动作unknown时继续保留无执行重叠与
显式核对规则。TTS降级后可停止/重启恢复，绝不自动重试原动作。
记忆语义见[记忆说明](online-agent-memory.md)。

启动终端 Ctrl+C 退出本次 Launch 创建的全部进程。在线入口关闭语音连接，
取消/回收录制与播放子进程，等待有界在线调用后释放 ROS。凭证、录音、
TTS音频、记忆、模型、SDK头和构建输出不提交。

## 可复现综合验收

停止麦克风入口，单独启动固定感知组合；探针自身组装交互并按序测试文本/WAV：

```bash
ros2 launch robot_bringup tracking.launch.py with_foxglove:=false
# 另一个已加载环境的终端，使用专用外部配置：
python3 ros2_ws/src/robot_agent/test/online_integration_probe.py \
  --config /absolute/external/test-config.json \
  --wav /absolute/path/to/existing.wav \
  --evidence-dir "$HOME/local-data/ros-robot/online-acceptance"
```

探针读取实际 dry_run 参数，验证真实图像/扫描、在线相机控制、fusion、
Follow、模拟/真实混合顺序、有意重复、WAV全链路，以及零运动消息/发布者。
使用专用验收配置（memory_summary_trigger=2），避免干扰日常记忆。
重新启动同一探针进程/配置，加--recall验证跨进程摘要召回与清空。
该阶段会清空专用记忆。失败记录仍保存，断言失败不能计为通过。

覆盖核对见[源业务清单](online-agent-inventory.md)，实际命令、结果、版本
与限度见[#68验收报告](online-agent-integration-validation.md)。
固定响应回归用于验证确定性失败/恢复语义，不能替代真实在线验收。


对于实际包含人物跟踪请求的既有录音，可另用 `--recording-only` 验证
录音识别后确实发出真实感知动作。探针先确认fusion并观察扫描，再提交
WAV，要求实际ASR文本非空且Follow动作有真实确认，最后停止跟随：

```bash
python3 ros2_ws/src/robot_agent/test/online_integration_probe.py \
  --config /absolute/external/test-config.json \
  --recording-only --wav /absolute/path/to/existing-tracking-request.wav \
  --evidence-dir "$HOME/local-data/ros-robot/online-acceptance"
```

文件名不参与识别或动作选择；只有服务端ASR/模型/设备结果满足条件才通过。
