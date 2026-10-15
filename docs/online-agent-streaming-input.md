# 持续ASR输入：设计与职责

正常麦克风使用持续PCM输入，不再先录固定时长WAV。WAV只在独立测试
中进行单次识别。保留旧robot项目的需求：暂停真实音频，连接继续保活；
LLM、动作、合成和播放结束后恢复监听，暂停期间的声音不能补发。

```text
PcmMicrophone → LiveSpeechInput → 完整句 → AgentApplication
      ↑              ↓                    ↓
持续读取PCM     自动暂停真实输入        会话/模型/动作/TTS/播放
暂停时丢弃      持续发送静音保活               ↓
      └────── 清理积压后恢复 ←──────────── resume
```

## Interface与所有权

- robot_audio.pcm_input.PcmMicrophone拥有唯一arecord进程，输出固定
  单声道PCM16/16kHz；start/read/discard/close隐藏管道与资源回收。
  read短轮询，EOF明确失败，close终止并回收子进程。
- voice.live_input.LiveSpeechInput拥有PCM源、一个ASR任务以及采集/接收
  两个I/O线程。listen只交付完整句；pause/resume/close管理真实输入与
  连接生命周期。传输线程持续工作，不等待业务处理或TTS完成。
- 迁移期输入生命周期只描述pause/resume/close，不再要求持续输入实现WAV识别。
  独立WAV输入把recognize_recording函数与生命周期一起注入AgentApplication；
  正常输入不支持submit_recording，明确拒绝，不另造一次性ASR连接。
- AgentApplication.run是唯一业务循环，await listen→submit_transcript顺序执行。
  无输入话题、请求队列、多入口接入锁或临时回合线程。内部Condition只
  协调采集、接收和单个最终句的资源交接；它不调度并发业务请求。

## 暂停、保活和恢复

接收线程确认最终非心跳句时，先暂停真实音频再交付。单个最终句槽在
暂停期间不再接纳请求。AgentApplication在整个LLM/动作/TTS/播放期间保持
暂停，finally请求恢复。正常暂停时仍消费麦克风PCM，以同样的100毫秒
音频帧节奏发送静音，不结束ASR任务，也不缓存播报或新的用户请求。

恢复由唯一采集线程执行：丢弃当前帧、部分帧及管道积压，记录已发送
音频的时间位置，再开始发送真实帧。接收线程用句子的begin_time过滤
恢复位置之前的迟到结果；暂停期间收到的结果直接丢弃。结果时间来自
已发送PCM长度，不使用模型文本推测是否回声。

协议字段与run-task/finish-task语义参照官方
[客户端事件](https://help.aliyun.com/en/model-studio/paraformer-client-events)和
[服务端事件](https://help.aliyun.com/en/model-studio/paraformer-server-events)。
heartbeat开启以支持长连接；心跳文本和中间句不进入交互。

## 失败和关闭

speech_timeout限制WAV识别/合成和持续PCM无帧等待，不用来结束正常
无人说话的长连接。持续输入每次握手最多min(speech_timeout,5)秒；
短接收轮询允许关闭及时取消。asr_attempts限制连续失败任务数，收到
有效最终句后重置；重连创建新任务，只发送新采集数据，不重放旧音频。
设备EOF/采集错误终止输入，不通过网络重连冒充恢复。耗尽后发布
asr_status=failed并停止监听，需操作者处理后重启，不自动重试模型/动作。

close取消设备和socket，然后等待传输Future；连接尚未返回时最多等
剩余握手期限，线程等待上限6秒，设备terminate等待1秒后kill回收。
正常活动连接和设备读取均可立即取消。编程错误继续显露，不能被报告为
普通语音成功。已有模型在途、动作未知和显式核对规则不变。

## 验证面

通过正常ROS结果话题和真实输入/网络Seam观察完整流程；通过PCM源与
WSS Adapter验证暂停仍读取设备、静音保活、恢复丢弃、迟到句过滤、有限
重连、异常收尾和关闭取消。固定传输测试不当作云端或实体设备验收。
真实在线验证使用用户已授权的生成语音作为外部PCM源，分别报告实体
麦克风/扬声器限度，ObjectTrack保持dry_run=true。
