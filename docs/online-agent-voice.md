# 在线麦克风与独立WAV验收

正常 `online_voice_agent` 只有麦克风输入，自动逐轮运行：

```text
录音 → 在线ASR完整句 → 唤醒/休眠/音乐规则
     → LLM/动作 → 可信回复 → 在线TTS/可选播放 → 下一轮录音
```

ROS主executor处理设备回执，唯一麦克风线程组织业务。没有输入话题订阅、
临时回合worker、接入busy调度、队列或会话锁。OnlineVoice与
OnlineInteraction的公共Interface要求同一调用者顺序调用；处理阶段状态
用于观测和静音计时，不作为并发输入锁。

OnlineVoice内部按入口和职责组织：

```text
submit_recording → _process_recording（ASR） → _process_text
submit_transcript → _process_text
    _decide_session → 必要时interaction.submit → _finish_turn
reconcile → _reconcile_turn（核对原动作并关联原文本）
```

三个入口均由_run_turn统一协调处理状态、暂停后恢复和活动时间。
临时回合记录只保存结果、文本和生命周期状态，不承担并发调度。
会话决策返回固定回执，或以None明确表示继续模型交互；忽略、过滤、
busy不合成，识别失败及空文本只记录。核对分支不发起新模型或动作。

## 外部配置与启动

依赖 Python3.8、ROS2 Foxy、`websocket-client>=1.6,<2` 与robot_audio。
正常录音还需要 `arecord`（alsa-utils），播放可选，开启时使用 `aplay`。
完整依赖和统一启动见[操作指南](online-agent.md)。

外部JSON配置示例（路径替换为源码外绝对路径）：

```json
{
  "api_key_env": "DASHSCOPE_API_KEY",
  "output_dir": "/absolute/external/online-results",
  "memory_file": "/absolute/external/conversation-summary.json",
  "record_device": "plughw:2,0",
  "record_seconds": 8,
  "asr_model": "paraformer-realtime-v2",
  "tts_model": "cosyvoice-v2",
  "tts_voice": "longfeifei_v2",
  "speech_timeout": 60,
  "provider_timeout": 60,
  "action_timeout": 5,
  "silence_timeout": 120,
  "tts_attempts": 3,
  "tts_failure_threshold": 5,
  "tts_retry_delay": 1,
  "memory_recent_turns": 6,
  "memory_summary_trigger": 6,
  "playback_enabled": false
}
```

`arecord -l` 查询实际麦克风；上例为当前板端USB麦克风。默认record_device
为default，record_seconds为8。录音后才在线识别，处理期间不录制下一段，
并非连续VAD。日志“开始麦克风录音”表示新采集窗口。
Agent不再定义dry_run或microphone_enabled配置和运行参数。
缺失设备由明确的模拟实现承担；ObjectTrack自身输出模式由其配置负责，
当前板端继续dry_run=true。感知服务负责TF、同步数据和近期扫描前提。

```bash
source /opt/ros/foxy/setup.bash
source /absolute/external/install/setup.bash
ros2 run robot_agent online_voice_agent --ros-args \
  -p config_file:=/absolute/external/config.json
# 观察回执，不能向正常入口提交text/WAV：
ros2 topic echo /online_agent/result std_msgs/msg/String
```

凭证仅环境读取，不写配置明文api_key。默认真实在线ASR/LLM/TTS使用
DashScope；端点与地域说明见[独立文本说明](online-agent-text.md)。
`record_executable`、`record_device`、`record_seconds`控制已有录音Adapter；
`playback_enabled=true`时，play_executable/play_device控制回复播放。
所有录音副本为临时文件；回复JSON/WAV及记忆放在源码外。

## 会话与执行生命周期

小沫、小莫、小墨、小末、小陌、小默各重复两次唤醒；唤醒后持续交互。
明确整句休眠或静音120秒回待机，子串不误触发。空识别和音乐过滤不刷新
静音期限。模型、动作、TTS或播放期间不因静音改变会话状态。
音乐状态来自同一动作注册表，只接受原音乐控制关键词。

ASR仅最终句进入交互，支持有限重连；暂停时有效音频停止，活跃连接发送
静音保活。单轮结束关闭连接，下一轮重建。TTS保留流式音频、有限重试与
连续失败文本降级；不重复模型或动作。显式enable_tts供单调用者在轮间恢复；
正常入口也可退出后重启恢复。动作回复只依据确认结果。

删除会话锁后仍保留实际执行约束：模型/摘要Future仍在途时，新提交返回
busy，不重叠外部调用；动作unknown保持待核对，线程结束不等于设备确认。
单调用者可通过reconcile(turn_id)核对迟到回执，不补执行剩余动作。
正常入口不开放文本控制话题；未知设备状态需操作者核实后停止/重启，不能
把自动重启当作动作成功。独立验收中可直接使用公共clear_memory、reconcile
与enable_tts Interface；退出后可删除专用记忆文件再重新开始。

Ctrl+C关闭语音连接、取消并回收录制/播放子进程，等待唯一业务线程结束，
随后销毁ROS节点。ASR、模型、TTS、文件或播放失败保留已有动作事实，
异常不会被替换为成功。语音连接关闭使用的传输锁只协调socket生命周期，
不承担会话或输入调度。

## 独立测试入口

文本测试单独运行 `ros2 run robot_agent online_agent`，不可与麦克风运行
混用；按每项完整回执再提交下一项，详情见[文本说明](online-agent-text.md)。

WAV单回合CLI仅处理文件，必须提供--wav；免唤醒，不启动麦克风：

```bash
ros2 run robot_agent online_voice_wav \
  --config /absolute/external/config.json --wav /absolute/path/existing.wav
```

WAV须为非空单声道PCM16、16kHz。该CLI默认模拟设备；需要真实感知时，
先启动tracking.launch.py，再单独运行[综合探针](online-agent.md)。
探针复用create_ros_voice，与正常入口同一Implementation和感知Adapter，
在自身进程顺序提交文本/WAV；不向正常麦克风节点发布输入。

固定回归、生成环境音与实际麦克风证据分别报告，不能相互冒充；新增验证
见[单麦克风重构报告](online-agent-microphone-validation.md)。
