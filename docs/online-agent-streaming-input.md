# 持续ASR输入：设计与职责

正常麦克风使用持续PCM输入，不先录固定时长WAV。WAV只在独立命令中
进行单次识别。暂停期间持续排空设备并发送静音保活；模型、动作、合成和
播放结束后恢复监听，暂停期间的声音不能补发。退出期间不恢复输入。

```text
AsyncPcmMicrophone → LiveSpeechInput → 完整句 → AgentApplication
      ↑                  ↓                         ↓
持续读取PCM         自动暂停真实输入       会话/模型/动作/TTS/播放
暂停时丢弃          持续发送静音保活                  ↓
      └──────── 清理积压后恢复 ←─────────────── resume
```

## Interface与所有权

- robot_audio.async_pcm_input.AsyncPcmMicrophone拥有唯一arecord子进程，
  输出固定单声道PCM16/16kHz。async start/read/aclose与同步discard隐藏
  非阻塞管道、部分帧和资源回收；EOF明确失败。
- LiveSpeechInput拥有PCM源、一个持久ASR任务、采集任务和网络任务。
  网络任务持有唯一发送者、接收者和重启等待者；所有业务状态归同一个
  asyncio主循环。listen只交付单个最终句，正常超时不结束ASR连接。
- AsyncSpeechConnection拥有连接、原握手任务和严格task-started校验。
  AsyncSpeechTask拥有原socket及关闭任务，发送背压不阻塞独立PCM采集。
- pause/resume同步控制真实音频、交接槽和最终句资格。独立文件识别使用
  RecordingInput.recognize/aclose及DashScopeASR；持续输入不实现WAV识别。
- AgentApplication.run是唯一业务循环，await listen→submit_transcript按序
  执行；ROS专用executor线程只交接设备回执。没有另一份语音业务循环、
  请求队列、回合线程或线程间音频Condition。

## 暂停、保活和恢复

接收任务确认最终非心跳句时先暂停真实音频再交付。单个最终句槽在暂停
期间不接纳下一句。应用在整个模型/动作/TTS/播放期间保持暂停，仍消费
PCM并按100毫秒帧节奏发送静音；既不缓存播报也不补发用户暂停期音频。

resume在事件循环同步丢弃当前帧、部分帧和管道积压，失效切换前的读取，
记录已发送音频位置。接收任务使用句子的begin_time过滤恢复位置之前的
迟到结果，暂停期间的结果直接丢弃。若旧帧仍阻塞在发送中则关闭旧任务后
重连，不在恢复后泄漏旧帧；位置来自PCM长度，不从模型文本猜测回声。

协议字段与run-task/finish-task语义参照官方
[客户端事件](https://help.aliyun.com/en/model-studio/paraformer-client-events)和
[服务端事件](https://help.aliyun.com/en/model-studio/paraformer-server-events)。
heartbeat开启以支持长连接，心跳文本和中间句不进入交互。

## 失败和关闭

speech_timeout限制文件识别/合成和持续PCM无帧等待，不结束正常无人说话
的长连接。每次连接和task-started握手共用min(speech_timeout,5)秒预算。
asr_attempts限制连续网络失败次数，仅有效最终句重置；重连只发送新采集
数据。设备EOF、采集错误和永久协议/鉴权故障不消耗网络重连尝试。
耗尽后发布asr_status=failed并停止监听，由操作者处理后重启。

应用第一次aclose建立shutdown_timeout总期限，stop先同步禁止新帧、最终
句和重连；所有后代使用同一绝对期限。连接获取、握手和发送/接收任务均
归原拥有者关闭，WebSocket握手关闭超出剩余预算时中止本地transport。
录音进程先terminate，保留预算给kill和reap；播放器同样回收原子进程。
并发aclose共享清理任务，取消等待者不会放弃资源。Python3.8的wait_for
可能让完成赢过取消，因此读取与网络循环在await前后检查已停止状态。

原动作回执交付在应用保存最终事实前保持有效；到期结束本地等待不代表
设备撤回。退出仍保存unknown与not_executed，保存失败和未分类编程错误
明确显露，其他资源继续清理。没有跨进程恢复、重放或自动补执行。

## 验证面

fixture使用真实loopback WebSocket、HTTP、隔离ROS和受控音频子进程。
应用关闭覆盖设备启动、连接、握手、首帧、阻塞发送/接收与重连；原有
暂停排空、静音保活、恢复过滤、单句交付和取消竞争测试继续保留。
本机fixture不代表云端模型、实体麦克风/扬声器或设备验收；tracking保持
当前dry-run配置。
