# 在线麦克风与独立WAV验收

正常 `online_voice_agent` 只有麦克风输入，自动逐轮运行：

```text
持续PCM → 在线ASR完整句 → 暂停真实音频、静音保活
       → 唤醒/休眠/音乐规则 → LLM/动作 → TTS/可选播放 → 清理并恢复
```

asyncio主循环持有应用；专用ROS executor线程只接收回执。
AgentApplication.run负责唯一listen→submit_transcript循环，ROS节点只接线
与发布结果。应用拒绝忙碌或关闭后的新回合，没有输入话题或请求队列。

完整回合可从AgentApplication.submit_transcript顺序阅读：接纳检查→暂停
输入→纯VoiceSession决定→必要时await Agent.submit→输出与记录→finally恢复。
应用独自持有processing/closed；VoiceSession只持有唤醒状态和活动时间，
不调用Agent、不执行I/O。空闲监听推进静音期限，处理期间不休眠。

独立WAV先await文件识别，再复用submit_transcript(direct=True)。
reconcile只核对原动作并关联原文本，不发起新模型或动作。忽略、过滤、
busy不合成；识别失败和空文本只记录。模型、语音、PCM和播放全部使用
原生异步I/O，业务调用者直接await公开入口；没有过渡阻塞Adapter。

## 外部配置与启动

依赖 Python3.8、ROS2 Foxy、`websockets==13.1`、`httpx==0.28.1` 与robot_audio。
正常录音还需要 `arecord`（alsa-utils），播放可选，开启时使用 `aplay`。
完整依赖和统一启动见[操作指南](online-agent.md)。

外部JSON配置示例（路径替换为源码外绝对路径）：

```json
{
  "api_key_env": "DASHSCOPE_API_KEY",
  "output_dir": "/absolute/external/online-results",
  "memory_file": "/absolute/external/conversation-summary.json",
  "record_device": "plughw:2,0",
  "asr_model": "paraformer-realtime-v2",
  "tts_model": "cosyvoice-v2",
  "tts_voice": "longfeifei_v2",
  "speech_timeout": 60,
  "shutdown_timeout": 5,
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
为default。正常入口连续读取PCM，不再按record_seconds切片；ASR最终句
决定回合。record_executable须持续输出原始单声道PCM16/16kHz，命令由
AsyncPcmMicrophone组装。连接建立前与重连中不缓存音频，准备完成后再说话。
Agent不再定义dry_run或microphone_enabled配置和运行参数。
缺失设备由明确的模拟实现承担；ObjectTrack自身输出模式由其配置负责，
当前板端继续dry_run=true。感知服务负责TF、同步数据和近期扫描前提。

```bash
./scripts/dev.sh ros run robot_agent online_voice_agent --ros-args \
  -p config_file:=/absolute/external/config.json
# 观察回执，不能向正常入口提交text/WAV：
./scripts/dev.sh ros topic echo /online_agent/result std_msgs/msg/String
```

凭证仅环境读取，不写配置明文api_key。默认真实在线ASR/LLM/TTS使用
DashScope；端点与地域说明见[模型与文本测试说明](online-agent-text.md)。
`record_executable`、`record_device`控制持续PCM录音Adapter；
`playback_enabled=true`时，play_executable/play_device控制回复播放。
独立WAV录音副本为临时文件；正常持续PCM不落盘。回复JSON/WAV及记忆放在源码外。

## 会话与执行生命周期

小沫、小莫、小墨、小末、小陌、小默各重复两次唤醒；唤醒后持续交互。
明确整句休眠或静音120秒回待机，子串不误触发。空识别和音乐过滤不刷新
静音期限。模型、动作、TTS或播放期间不因静音改变会话状态。
音乐状态来自同一注入能力，只接受原音乐控制关键词。

ASR仅最终句进入交互，支持有限重连；暂停时有效音频停止，活跃连接发送
静音保活。正常ASR跨回合保持任务，暂停期间读取并丢弃麦克风数据，恢复前清理积压
并过滤迟到旧句。独立WAV仍在单次识别结束后关闭其连接。TTS保留流式音频、有限重试与
连续失败文本降级；不重复模型或动作。显式enable_tts供单调用者在轮间恢复；
正常入口也可退出后重启恢复。动作回复只依据确认结果。

删除会话锁后仍保留实际执行约束：模型/摘要调用仍在途时，新提交返回
busy，不重叠外部调用；动作unknown保持待核对，本地Task结束不等于设备确认。
单调用者可通过reconcile(turn_id)核对迟到回执，不补执行剩余动作。
正常入口不开放文本控制话题；未知设备状态需操作者核实后停止/重启，不能
把自动重启当作动作成功。独立验收中可直接使用公共clear_memory、reconcile
与enable_tts Interface；退出后可删除专用记忆文件再重新开始。

Ctrl+C首先同步停止新回合、音频、模型/合成重试和所有后续设备步骤。
shutdown_timeout默认为5秒，必须为正有限秒数；第一次关闭建立唯一绝对
总期限，输入、输出、模型和设备回执收尾共享剩余预算。并发关闭共享原
清理任务，取消等待者不能放弃资源回收。期限内保留原ROS回执交付，保存
确认事实、unknown和not_executed后才关闭ROS executor；本地等待取消不
代表设备动作撤回。已经完成的WAV和动作事实不受后续播放或保存故障影响。
退出记录复用原turn_id的JSON；保存失败以异常明确报告。多个清理故障保留
原始错误，其他必要Closer仍执行；没有重放、自动补执行或跨进程恢复。

持续输入的任务、资源、失败与恢复规则见[设计说明](online-agent-streaming-input.md)。

## 独立测试入口

文本测试直接await build_agent(config).submit(text)，不启动ROS文本
节点，详情见[模型与文本测试说明](online-agent-text.md)。

WAV单回合CLI仅处理文件，必须提供--wav；免唤醒，不启动麦克风：

```bash
./scripts/dev.sh ros run robot_agent online_voice_wav \
  --config /absolute/external/config.json --wav /absolute/path/existing.wav
```

WAV须为非空单声道PCM16、16kHz。该CLI默认模拟设备；需要真实感知时，
先启动tracking.launch.py，再单独运行[综合探针](online-agent.md)。
探针复用create_ros_application，与正常入口同一Implementation和感知Adapter，
在自身进程顺序提交文本/WAV；不向正常麦克风节点发布输入。

固定回归、生成环境音与实际麦克风证据分别报告，不能相互冒充；新增验证
见[单麦克风重构报告](online-agent-microphone-validation.md)。
