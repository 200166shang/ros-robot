# #67 在线语音验收记录

日期：2026-10-14（北京时间）。独立 worktree `ros-robot-67`，
分支 `codex/issue-67-online-voice`，实施前 fetch 最新主线，基线
`13ef19b3c59483f0717c10da6ca8e69b6b011f46`（#64 已关闭）。

## 真实在线证据

使用现成 `/home/orangepi/mic-smoke.wav`（单声道 PCM16 16kHz，8秒），
未生成替代输入，未用文件名或预知文本作为识别结果。实际 ASR 文本：
“你好机器人。请报告当前状态。”。默认原提示词、paraformer-realtime-v2、
qwen-plus、cosyvoice-v2 / longfeifei_v2；凭证仅环境读取。
所有缺失设备动作保持模拟，麦克风和回复播放关闭。

源码运行 `online_voice_runtime --config <外部配置> --wav <已有录音>`：

- turn `3d45a4f96ca842859eb6edd36691cc94`，completed；
- 模型提出 wake_up、head_forward、head_listen，按序模拟成功；
- 合成文本为确认后的模拟回执，未播报模型提前成功承诺；
- 真实在线 TTS WAV：13.81秒，16kHz、单声道 PCM16；
- 音频 SHA256：`a520a16bfaa7c02468457587200b928386f1868d5475000468bd384558aaa733`。

外部安装版从 `/tmp` 运行真实 ROS 2 probe，`ROS_DOMAIN_ID=167`，
在 `/online_agent/wav` 发布相同旧录音，在 `/online_agent/result` 接收结果：

- turn `ae9540d9a3ec40758ffc167840a4625c`，completed；
- 真实 ASR 文本同上；真实 LLM 提出 wake_up、head_forward、
  navigation_status、show_wifi_info、volume_status、music_status；
- 六项动作均为 simulated_success，回复明确每项模拟结果；
- TTS completed，WAV 为42.07秒，16kHz、单声道 PCM16；
- 音频 SHA256：`1f79dd2e8490340bd5f318c998616a8e5afd7b9e8a86865433b71c86e05a79ce`；
- `/cmd_vel` 订阅收到 **0** 条消息；退出释放连接、线程和 ROS 节点。

另以已有 unsafe_motion_request_zh_2026-09-24.wav 完成普通回复：
ASR 实际识别“机器人，请让底盘向前移动20厘米。”，模型拒绝未支持的移动，
零动作；turn `a616d16a787e48d6a696773bb04e916c`，TTS为18.17秒。

原始 JSON、WAV、非敏感配置、probe、首轮失败记录都在源码外：
`/home/orangepi/local-data/ros-robot/issue-67-evidence/`。
构建在 `/home/orangepi/local-data/ros-robot/issue-67-build/`；
验收依赖和工具在 `/home/orangepi/local-data/ros-robot/issue-67-venv/`。

### 观察到的连接问题

首次通过现有 HTTP 代理连接 WSS，握手后任务启动事件超时；有限期限结束，
返回 asr_status=failed，零动作。针对 DashScope 域名设置
`NO_PROXY=dashscope.aliyuncs.com` 与 `no_proxy=dashscope.aliyuncs.com`
后直连立即收到 task-started，以上真实链路通过。不修改系统代理配置。
第一份旧 tts-smoke.wav 因22.05kHz被输入 Interface拒绝；验收采用原生
16kHz旧录音。单独重采样的诊断副本只在源码外，不用作上述动作验收输入。

## 行为与质量验证

- 第一个录音回合测试先因 OnlineVoice 不存在失败，实现后通过。
- 半双工时序测试先观察到模型期间未暂停采集，修正后通过。
- 迟到回执核对测试先因缺少语音 reconcile Interface 失败，复用原交互
  核对后通过，不重发原动作，也不补执行超时后的动作。
- 13项新增语音行为测试通过：录音免唤醒、六种同音唤醒、连续会话、精确
  休眠/子串不误吞、静音、真实模拟音乐状态过滤、TTS重试/连续失败降级/
  显式恢复、失败后释放回合、忙拒绝、关闭、迟到动作核对、播放失败。
- 固定真实传输协议事件验证 ASR 断线重连、只接纳最终句、心跳过滤、
  暂停静音保活、恢复不丢源音频、总期限和关闭；TTS分片形成有效WAV，
  部分音频后失败删除临时文件。固定事件不作为真实云端通过证据。
- robot_voice 与 robot_agent 外部 `colcon build` 通过；安装版真实 ROS
  probe 通过。Ruff format/check 和新增模块 Pyright 检查通过。

最终全量回归和双轴审查复验结果在提交 PR 前补充。

首次双轴审查各发现一项问题，已按纵向行为测试修复：保存失败保留原回合
事实，以 record_status=failed 标记；正常退出通过取消信号终止/回收在途
录音与播放子进程。两个公开音频 Interface 测试先因缺少取消参数失败，
实现后通过；确认取消返回前进程已退出，而不是仅停止等待。

## 范围

本票不接入 #65 感知或 #66 记忆实现，综合运行由 #68 验收。
未启用麦克风采集或真实播放，二者为可选入口，不是必验项。
ASR双向音频流、LLM SSE、TTS音频流均保留；业务收齐模型结构化输出后
执行动作并合成最终回复，普通聊天同样使用这一安全输出时序。
