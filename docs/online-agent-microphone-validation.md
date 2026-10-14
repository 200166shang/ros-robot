# #68 单麦克风重构验收

2026-10-14，PR #75 的后续实现。基线为 `1802815`，沿用独立
worktree `/home/orangepi/code/ros-robot-68`。本报告覆盖用户确认的
第一、二项：简化逐轮接入、删除 Online Agent 的 `dry_run`。
第三项功能目录迁移未实施。最初交付证据见
[原综合验收](online-agent-integration-validation.md)。

## 实现与契约

正常入口仅启动一个持续麦克风线程，按以下顺序运行：

```text
录音 → 在线 ASR → 唤醒/休眠规则 → LLM/动作 → TTS → 恢复录音
```

删除正常节点的 text/WAV/transcript/文本控制订阅、每轮临时线程、
接入忙碌分支和会话互斥锁。Interface 由单一调用者逐轮使用。
空 ASR 不刷新活动时间，避免持续空录音阻止静音休眠。
退出先取消语音资源并等待麦克风线程结束，再销毁 ROS 节点。
模型仍在途、动作结果未知时的无重叠及显式核对规则继续保留。

独立文本/WAV 测试进程复用同一交互实现与 ROS 设备适配器，
正常语音运行时不开放这些入口。Online Agent 不再声明或检查
`dry_run`，也不重复查询设备模式；未接入设备由明确的模拟实现
承担。ObjectTrack 自身仍保持 `dry_run=true`，其设备前提由
ObjectTrack 检查。本次没有授权硬件运动。

## 自动生成环境语音

实体 USB 麦克风试验未完成连续对话：多数 ASR 为空，另有一次
无关语句。用户因此明确要求自动生成音频作为环境音跑通。
这不是实体麦克风修复或实体录音验收。

使用真实 DashScope TTS 生成下列输入，均为单声道、16kHz、
PCM16 WAV；文件、完整 SHA256 和生成清单位于源码外证据目录。

| 输入文本 | 时长 | 在线 ASR 实际回执 | 结果 |
| --- | --- | --- | --- |
| 小沫小沫 | 1.24秒 | 小莫小莫。 | woken，回复“我在，请说。” |
| 请点头两次 | 1.32秒 | 请点头两次。 | completed，两个 head_nod 均模拟成功 |
| 晚安 | 0.76秒 | 晚安。 | sleeping，恢复待机 |

通过已有 `record_executable` 配置接入源码外录音适配器。
适配器依次提供三段 WAV，正常节点仍经过麦克风采集 Interface、
在线 ASR、LLM、动作与 TTS；没有注入 transcript 或替换在线服务。
这次验证的是模拟环境音源，不是通过扬声器向实体麦克风播放。
三个回复均 `tts_status=completed`，生成可核查回复 WAV。
第三轮后下一次录音等待被正常退出取消。

运行时 ROS 检查确认 Agent 只有 `config_file`、`use_sim_time`
参数；六个旧输入/控制话题的订阅数均为0；ObjectTrack 的
`dry_run=true`。`/cmd_vel`、`/tracking/cmd_vel_safe` 发布者为0，
观察到的运动消息也为0。

## 独立在线验收

停止正常麦克风节点，单独启动固定感知 Launch 与测试进程。
新验收入口要求 `--config`，直接复用 `create_ros_voice`，
不向正常节点发布文本/WAV 输入。

- integration：8轮 completed；真实相机、雷达、跟随启停与模拟
  音量/点头结果按顺序核验；扫描509帧、图像569帧、运动消息0。
- recall：3轮 completed；跨进程回忆“蓝鹭”、清除记忆、
  清除后不再回忆均通过。
- recording-only：3轮 completed；已有录音实际 ASR 为
  “开始人物跟踪。”，启动图像接收及融合人物跟踪得到真实设备
  确认，随后停止跟随；运动消息0。

以上14轮中清除记忆不生成语音，其余13轮 TTS 完成。
连同环境音流程，共核验16个回复 WAV 的格式、时长和 SHA256。
感知验收没有真实人物目标；语音播放关闭，未验证扬声器。

模型自由聊天回忆中额外声称“没有执行任何动作”，与历史记录
不符。昵称回忆测试通过，但该自由聊天陈述不能作为动作证据；
动作事实以回合结构化结果及设备回执为准。

## 可复现入口与证据

沿用原报告的源码外构建环境。正常运行示例：

```bash
source /opt/ros/foxy/setup.bash
source /home/orangepi/local-data/ros-robot/issue-68-build/install/setup.bash
ros2 launch robot_bringup online_agent.launch.py \
  config_file:=/home/orangepi/local-data/ros-robot/issue-68-microphone-refactor/environment-config.json
```

独立验收需单独运行固定感知 Launch，命令见
[当前指南](online-agent.md)。测试进程示例：

```bash
python3 ros2_ws/src/robot_agent/test/online_integration_probe.py \
  --config /home/orangepi/local-data/ros-robot/issue-68-microphone-refactor/standalone-config.json \
  --wav /home/orangepi/local-data/ros-robot/voice-fixtures/start_person_tracking_zh_2026-09-24.wav \
  --evidence-dir /home/orangepi/local-data/ros-robot/issue-68-microphone-refactor/standalone \
  --recording-only
```

凭证从源码外环境导入。当前外部环境音适配器使用单次递增索引，
重跑前须把证据目录的 `environment-index` 重置为0。

证据根目录：
`/home/orangepi/local-data/ros-robot/issue-68-microphone-refactor/`。
关键文件为 `environment-audio/manifest.json`、
`environment-results.json`、`runtime-contract.json`、
`standalone/{integration,recall,recording}.json`、
`reply-audio-manifest.json`，以及对应 Launch/测试日志。
录音、记忆、配置、凭证、构建输出均未进入源码提交。

## 自动检查

Python3.8.10、ROS2 Foxy、pytest6.2.5、Ruff0.17.0、
Pyright1.1.414。先验证旧实现失败，再验证新行为通过：正常节点
无多入口/Agent 参数、无需 Agent 设备模式查询、空 ASR 静音到期。

- 最终 Python 全套：98 passed（11.66秒）。
- 修改的10个模块 Pyright：0 errors、0 warnings。
- Ruff 格式检查41个文件，lint 通过；`git diff --check` 通过。
- 源码外增量构建 robot_agent、robot_bringup：2包成功。

- 源码外8包 colcon 测试：30 tests，0 errors，0 failures，
  0 skipped。robot_agent 的 setuptools 任务仍发现0项，
  它的行为测试包含在上述独立 Python 全套98项中。

双轴代码审查：Standards 首轮1项发现涉及2处过期契约注释，
已修正并复审；最终 Standards 0项剩余发现、Spec 0项发现。

## 设备音频工具抽离（2026-10-15）

用户进一步授权抽离共享设备音频工具。以本报告上一轮提交
`c50391e` 为基线，把 audio_io、audio_sources 和对应行为测试
迁入 robot_audio；在线 robot_agent 与现有 robot_voice 均直接
依赖它。robot_audio不启动ROS节点，不包含ASR/TTS或模型。
未增加common框架，也没有实现新离线方案。旧导入路径已删除，
安装部署需重新构建新包及两个调用包。

```text
robot_agent（在线ASR/TTS） → robot_audio ← robot_voice（本地ASR/TTS）
                            录音 / WAV / 播放
```

保留采集/播放的取消、超时、子进程回收及WAV格式契约。
现有离线前端仅更新导入并按根Ruff配置整理格式与说明。
在线感知、模型和语音流程未改变，没有新增topic或进程。

- 迁移后最终Python回归98 passed（11.58秒），其中设备音频
  工具5项测试迁入新包；在线麦克风相关单项先检查16项通过。
- Ruff45文件格式和lint、`git diff --check`通过。
- 新音频包与在线组装模块Pyright零错误/警告。
- 离线前端存在27项旧ROS参数类型诊断；对迁移前后独立检查，
  诊断内容完全相同，没有新增。未借本次迁移重构其参数逻辑。
- 全新源码外构建目录
  `/home/orangepi/local-data/ros-robot/issue-68-audio-build/`：
  robot_audio、robot_agent、robot_voice三包构建成功（23.2秒）。

- 从/tmp加载全新安装环境，确认在线/离线引用同一份
  robot_audio.create_audio_source；安装版音频测试5 passed。
- 三包colcon test任务成功：robot_audio执行3项文件源测试，
  robot_voice执行3项识别解析测试；robot_agent的setuptools任务
  发现0项，其实际行为包含在完整98项pytest中。新构建目录的
  setuptools任务未生成JUnit XML，不使用test-result的0项作为
  行为覆盖证据。日志为audio-clean-test.log。

上述检查日志位于同一源码外证据目录，文件名前缀audio-。
联合收集时曾观察到两个名为test的Python包冲突，已把新包测试
目录命名为tests；最终98项回归包含该修正。运行Interface未改变。
双轴审查首轮及目录修正后复审：Standards/Spec均0项剩余发现。
