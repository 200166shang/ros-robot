# 在线语音与会话（#67）

语音入口复用 `robot_voice.audio_sources` 的 `capture(destination)` Interface，
已有 WAV 可直接提交一回合，不需要唤醒词。输入契约仍为非空单声道 PCM16
16kHz WAV。默认关闭麦克风和播放；ASR、模型、TTS 均真实在线，头部、导航、
音乐、音量与 WiFi 使用 #64 的完整模拟状态，保持 `dry_run=true`。

## 运行

依赖 Python 3.8+、`websocket-client>=1.6,<2` 及既有 robot_voice 包。
DashScope SDK 不参与运行；语音 Adapter 直接使用服务端双向 WebSocket 协议。
模型沿用现有 DashScope SSE Adapter 和提示词。

把配置保存到源码外，例如 `~/local-data/ros-robot/voice/config.json`：

```json
{
  "dry_run": true,
  "api_key_env": "DASHSCOPE_API_KEY",
  "output_dir": "/home/orangepi/local-data/ros-robot/voice/results",
  "asr_model": "paraformer-realtime-v2",
  "asr_attempts": 2,
  "tts_model": "cosyvoice-v2",
  "tts_voice": "longfeifei_v2",
  "tts_attempts": 3,
  "tts_failure_threshold": 5,
  "tts_retry_delay": 1,
  "speech_timeout": 60,
  "provider_timeout": 60,
  "action_timeout": 5,
  "silence_timeout": 120,
  "microphone_enabled": false,
  "playback_enabled": false
}
```

凭证由所指定的环境变量读取，禁止配置明文 `api_key`。可用
`speech_endpoint` 配置所在地域的 WSS 语音端点，模型 HTTP 配置保持原契约。
本环境 HTTP 代理建立 WSS 后未返回任务事件；验证时对
`dashscope.aliyuncs.com` 设置 `NO_PROXY` 和 `no_proxy`，使用直连。

```bash
source /opt/ros/foxy/setup.bash
source /path/to/external/install/setup.bash
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}dashscope.aliyuncs.com"
export no_proxy="$NO_PROXY"
online_voice_wav --config ~/local-data/ros-robot/voice/config.json \
  --wav /path/to/existing.wav
ros2 run robot_agent online_voice_agent --ros-args \
  -p dry_run:=true -p config_file:=/path/to/external/config.json
```

CLI 的 `--wav` 缺省时，仅在 `microphone_enabled=true` 才调用麦克风。
麦克风采用既有 arecord Adapter，`record_executable`、`record_device`、
`record_seconds` 可配置；每轮录制结束后识别，再等待回复合成/播放完成，
然后开始下一次录制。播放启用后通过既有 aplay Adapter 输出已保存 WAV；
`play_executable`、`play_device` 可配置。播放失败保留音频及动作事实。
正常退出关闭 ASR/TTS 连接，取消在途 arecord/aplay 并回收子进程，
等待有界模型调用后释放 ROS。

## ROS Interface

仅启动一个在线入口，避免文本版与语音版竞争同名话题。

| 输入话题（std_msgs/String） | 语义 |
|---|---|
| `/online_agent/wav` | 源码外 WAV 路径，直接单回合 |
| `/online_agent/text` | 既有直接文本语义，加在线 TTS |
| `/online_agent/transcript` | 最终识别文本事件，遵循唤醒和连续会话 |
| `/online_agent/reconcile` | 原 turn_id 核对迟到回执，不重发动作 |
| `/online_agent/tts_enable` | 内容 `enable` 显式恢复 TTS，忙时不重置 |

所有回执在 `/online_agent/result` 发布。相同 `turn_id` 关联识别文本、可信
回复、动作参数/结果、会话状态与音频路径。对应 `<turn_id>.json` 和
`<turn_id>.wav` 保存在 `output_dir`，临时录音副本处理后删除。
记录写入失败返回 `record_status=failed`，仍保留原 turn_id、动作事实、
回复与已生成音频路径；ROS不会将后阶段失败改写成零动作的新回合。
产物、记忆、凭证、录音、模型与构建输出都不进入源码提交。

## 会话状态与交接

```text
standby --六种重复唤醒词--> listening
listening --普通请求--> processing --回复结束--> listening
listening --精确休眠指令/静音120秒--> standby
standby --直接录音或文本--> processing --回复结束--> standby
任意状态 --退出--> closed
processing --并发输入--> busy（不排队，不打断）
```

唤醒词为小沫、小莫、小墨、小末、小陌、小默，各重复两次；识别标点不影响
匹配，唤醒句仅用于唤醒。连续会话不要求重复唤醒。旧休眠短语保留为整句
匹配，去除标点和空格后比较；例如“好了”进入待机，“好了以后请点头”仍为
普通请求。静音计时在回合完成后重新开始，处理期间不因超时改变会话。

音乐播放状态直接读取同一个 ActionRegistry 的 MusicSimulation。
播放中只接受原音乐控制关键词，包括停止/关闭、切歌/上一首/下一首、
播放/恢复播放、音量/声音/静音；唤醒和明确休眠仍可使用。
被过滤的输入不延长静音期限。直接录音/文本绕过会话过滤，供独立验收。

ASR 按100毫秒 PCM 帧发送，最终句才进入交互，不把中间文本或心跳当输入。
`pause/resume` 控制有效音频；存在活跃识别连接时暂停发送静音保活，恢复不
丢失剩余录音。单回合结束主动关闭连接，模型/动作/TTS期间无需保留空闲
ASR连接；下一次输入重新建立。断线整轮有限重连，失败连接的句子丢弃，
所有尝试共享 `speech_timeout` 总期限。关闭后不再重连。

LLM 保留 SSE 分片，交互收齐结构化输出并整表校验，动作确认后才合成最终
语音；TTS 流式音频直接写临时 PCM WAV，收到 task-finished 且有音频才原子
提交成功文件。模型的提前成功承诺不会被播报。当前普通聊天也收齐回复后
合成，未增加提前解析 JSON 回复的通道。

TTS 每轮有限重试，重试不重复模型或动作；连续失败回合达到阈值后降级为
文本，显式 enable 可恢复。识别、合成、播放或保存异常均释放语音回合锁；
已有交互的模型在途/设备未知结果仍保持其安全互斥契约，不自动重试动作。

## 协议参考

- [Paraformer 客户端事件](https://www.alibabacloud.com/help/en/model-studio/paraformer-client-events)
- [Paraformer 服务端事件](https://www.alibabacloud.com/help/en/model-studio/paraformer-server-events)
- [CosyVoice 客户端事件](https://www.alibabacloud.com/help/en/model-studio/cosyvoice-client-events)
- [CosyVoice 服务端事件](https://www.alibabacloud.com/help/en/model-studio/cosyvoice-server-events)
