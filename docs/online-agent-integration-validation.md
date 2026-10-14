# #68 统一启动与综合验收

本报告记录最初PR交付版本。用户确认的单麦克风与删除Agent模式的后续
实现/验收见[单麦克风重构报告](online-agent-microphone-validation.md)，
操作以[当前指南](online-agent.md)为准；下文历史命令和证据保留。

2026-10-14（北京时间）。独立 worktree `/home/orangepi/code/ros-robot-68`，
分支 `codex/issue-68-online-integration`。实施前 `git fetch origin main`，
基线 `0bfb5477b57c5830b4cda68140a892e86d9add4f`，包含 #63–#67全部交付。

## 交付与源功能覆盖

`robot_bringup/online_agent.launch.py` 一次组合固定感知 Launch 与
`online_voice_agent`，一个入口处理文本、录音、可选麦克风、记忆及真实感知。
必填外部 config_file，dry_run 固定 true，可视化默认关闭。正常 Launch
管理子进程，无第二监督器，无旧PWM权限修改。补齐完整语音ROS入口的
启动/错误提示音日志模拟，复用 #64 simulate_cue，不播放提示音。

[统一指南](online-agent.md)提供依赖、构建、外部配置、输入、恢复及退出。
[源清单](online-agent-inventory.md)逐项核对旧版本 `22cd28d`：60项源动作
及参数集合全部接受、默认值差异0，52模拟+8真实感知；另外7项兼容名保留。
头部/LCD/导航/音乐/音量/WiFi按职责持有状态，交互集中组织回合，真实
provider/ROS/音频在边缘，未新增动作类、插件框架或未讨论业务。

## 环境、数据与命令

Python3.8.10、ROS2 Foxy、YDLIDAR SDK1.2.7、Ruff0.17.0、
Pyright1.1.414、pytest6.2.5。沿用已有板端RKNN模型和MPP/RGA后端。
源码外证据目录 `/home/orangepi/local-data/ros-robot/issue-68-evidence/`，
构建目录 `/home/orangepi/local-data/ros-robot/issue-68-build/`。

非敏感配置为 qwen-plus、paraformer-realtime-v2、cosyvoice-v2 /
longfeifei_v2，dry_run=true；provider/speech_timeout=60秒，
action_timeout=5秒；memory_recent_turns=2、memory_summary_trigger=2；
麦克风/播放关闭。output_dir为专用turns子目录、memory_file为专用文件。
凭证从源码外文件导入环境，不输出内容；本进程的NO_PROXY/no_proxy仅追加
DashScope域名，沿用 #67 已观察到的 WSS 代理阻塞恢复方式。

```bash
source /opt/ros/foxy/setup.bash
source /home/orangepi/code/ros2_ws/install/setup.bash
source scripts/ydlidar-sdk-env.zsh
colcon --log-base /home/orangepi/local-data/ros-robot/issue-68-build/log build \
  --base-paths ros2_ws/src \
  --build-base /home/orangepi/local-data/ros-robot/issue-68-build/build \
  --install-base /home/orangepi/local-data/ros-robot/issue-68-build/install \
  --packages-up-to robot_bringup robot_voice --executor sequential \
  --cmake-args -DRKNN_API_INCLUDE_DIR=/home/orangepi/sdk/rknn/include
source /home/orangepi/local-data/ros-robot/issue-68-build/install/setup.bash
# 外部环境导入Key后，统一入口实际命令（ROS_DOMAIN_ID=181）：
ros2 launch robot_bringup online_agent.launch.py \
  config_file:=/home/orangepi/local-data/ros-robot/issue-68-evidence/config.json
python3 ros2_ws/src/robot_agent/test/online_integration_probe.py \
  --wav /home/orangepi/mic-smoke.wav \
  --evidence-dir /home/orangepi/local-data/ros-robot/issue-68-evidence
# Ctrl+C结束，再用相同配置重启Launch，执行同一探针加 --recall。
```

首次构建命令漏传RKNN外部头目录，在detector配置阶段失败；上面补齐参数
后复验。没有将头文件复制进源码。第三方YDLIDAR/RGA既有编译警告保留。

## 确定性行为与规范检查

ROS_DOMAIN_ID=182，加载Foxy，以系统Python及源码robot_agent/robot_voice，
外部工具依赖目录加入PYTHONPATH：

```bash
python3 -m pytest -q tests ros2_ws/src/robot_agent/test \
  ros2_ws/src/robot_voice/test ros2_ws/src/robot_bringup/test
ruff format --check .
ruff check .
pyright ros2_ws/src/robot_agent/robot_agent/online_voice_ros_node.py \
  ros2_ws/src/robot_agent/test/online_integration_probe.py \
  ros2_ws/src/robot_bringup/launch/online_agent.launch.py \
  ros2_ws/src/robot_bringup/scripts/tracking_control_acceptance_probe.py
```

完整Python回归初轮 **95 passed，12.57秒**；修正固定探针后最终回归
**95 passed，8.77秒**；审查修复后的最终回归为 **96 passed，9.68秒**。新增Launch测试先因入口文件不存在
失败，实现后通过；确认必填配置、单一在线入口、固定跟踪组合和默认关闭
可视化。语音/感知/记忆组装单文件与新Launch合计2项通过。
Ruff按根配置最终检查39文件，格式及E/W/F/I通过；新Launch与修改的固定探针显式加入检查范围，
新online探针/测试自动命中既有模式。类型检查0 errors、0 warnings。

| 综合行为 | 确定性公开Interface证据 |
|---|---|
| 顺序、有意重复、跨轮重复、流式片段只执行一次 | test_online_interaction / test_online_simulation |
| 整表预校验零执行、运行失败停止、可信回复 | test_online_interaction / test_online_perception |
| busy、超时、在途未知、迟到核对、无动作重试 | test_online_interaction / test_online_perception_ros |
| 后续报告失败保留已执行事实、剩余列表 | test_online_interaction / test_online_voice |
| 有界近期上下文、摘要重启、清空、保存失败 | test_online_memory / test_online_memory_ros |
| 语音与感知/记忆同一回合组装 | test_online_voice_integration |
| 唤醒、连续会话、精确休眠、静音、音乐过滤 | test_online_voice |
| ASR重连/总期限、采集恢复、TTS重试/降级/显式恢复 | test_online_speech / test_online_voice |
| 录制/播放取消回收、不留成功的部分音频 | test_audio_io / test_online_speech |

人工检查中文docstring、公共类型、编号流程、语义空行和模块职责。
新增Launch仅组合已有入口；探针通过公开ROS话题/参数观察运行，失败直接
断言、finally保留证据。提示音仅按既有失败状态记录日志。没有新增默认
设备成功、自动动作重试、宽泛异常捕获或静默吞掉编程错误。dry-run参数与
设备回执校验继续在既有ROS Adapter边缘，主链不重复校验。

## 真实在线综合结果

统一Launch由 `/tmp` 启动最终安装包，探针只通过公开话题接入，不另建Agent。
三个阶段原始证据为integration.json、recall.json、recording.json，
**8+3+3=14回合全部completed**（清空1回合不合成，其余13回合TTS与记录
均completed，memory_warnings=[]）。所有语音、模型及服务调用都真实在线。

| 阶段 | 实际结果 |
|---|---|
| 相机恢复、融合 | start_receiving_image请求发布；enable_lidar真实确认 |
| 混合回合 | volume_set(35)→start_following→head_nod→head_nod→volume_status→stop_following；模拟/真实/模拟/模拟/模拟/真实，音量35，Follow启用后正常待机并关闭融合 |
| 相机暂停/恢复 | 先确认Follow待机，发布false，再发布true；未冒充硬件确认 |
| 旧mic-smoke.wav | 实际识别“你好机器人。请报告当前状态。”；本轮模型纯回复，未将零动作当作录音动作通过 |
| 记忆及重启 | 告知代号蓝鹭，两轮在线摘要保存；结束完整Launch后，新进程直接召回蓝鹭 |
| 清空 | clear完成；再次提问回复“我们还没有约定过验收代号”，未再召回蓝鹭 |
| 旧人物跟踪WAV | 实际识别“开始人物跟踪。”，模型选择start_tracking，真实fusion/Follow回执确认，在线TTS完成；随后stop_following真实停止并关闭融合 |

混合回合 `ad20a26ba304485da6ecd0657ddcc8ca` 保留重复动作与真实Follow事实。
录音动作回合 `e59ef0fd6e914e0dae0d7ba41bb43461` 使用既有
`voice-fixtures/start_person_tracking_zh_2026-09-24.wav`（1.47秒，原生16kHz），
输入文件未重录、未重采样，文件名不参与识别。该阶段命令为上面探针加
`--recording-only --wav /home/orangepi/local-data/ros-robot/voice-fixtures/start_person_tracking_zh_2026-09-24.wav`。
融合确认后另行观察至少两帧真实扫描，再提交该WAV，无动作重试或弱化前提。

三个阶段分别观察真实scan 568/41/133帧，检测标注图像565/37/157帧。
两个运动话题消息均0，两个运动话题发布者均0；探针开始读取实际Agent及
ObjectTrack参数为dry_run=true。实际相机约15fps、RKNN约9fps，真实雷达扫描。
相机初次capture timeout后由既有驱动重开成功；RKNN既有core-mask无实现
提示未阻止真实检测，不修改驱动/算法。场景未出现人物目标，不声称完成
人物运动轨迹验收；Follow服务仍按实际同步数据/扫描/TF前提确认启用。

两次Ctrl+C均正常退出本Launch的全部7个子进程，雷达停止扫描；没有遗留
本轮在线或硬件进程。原始配置/回执/记忆/日志/WAV均在源码外，
memory-before-restart.json保留重启前真实摘要。未输出或提交Key。

### 可试听音频

13份TTS均通过WAV读取核查：单声道PCM16、16kHz、非零帧。所有音频按
turn_id在外部turns目录，可本地直接试听；全部时长/校验值在audio-evidence.json。

| 回合 | WAV秒数 | SHA256 |
|---|---:|---|
| 文本混合动作 ad20a26b… | 44.71 | 37085c0e4400039f5a1bc93d3fd7ee7c9f77f07b6bac605d26455891092c87d1 |
| 旧状态WAV 66ca93a0… | 24.91 | d13e38d031a29d5d0089f5ed8086d354423b9a24eaca41fd845ac0ed9245437f |
| 旧跟踪WAV e59ef0fd… | 11.41 | 87912debccde84f729b3890614a18753a55e3dfde3d7f87b9c9cc39249ead5fa |
| 重启召回 05c78cf7… | 3.09 | 6cc4313b583ed8b7da523eb7811de0e38a44ae3f8c2bfe35a8b1a31a86f17c3b |


## 固定跟踪探针复验与限度

使用独立ROS_DOMAIN_ID=183，实际ObjectTrack与平台TF，输入为原样例
图像/检测/扫描（固定样例测试，不计为实机或真实在线证据）。先运行原探针：
`AcceptanceFailure: timed out waiting for dry-run preview containing no target found`。
原始fixed-probe.log与fixed-tracker.log保留。复现 #65原限度，未改写旧报告。

最小场景测得1280×720样例图像传输约1.84秒，而tracker要求扫描1秒内新鲜。
去掉前置步骤后可通过，说明原场景有时序依赖。按顺序验证三项假设：扫描
随图像单发导致过期；预览节流延迟；日志接收丢失。首先只改变采样：外部
实验独立10Hz扫描，样例/算法/断言期限不变，完整原探针通过，实测131帧、
扫描最大间隔0.106秒。continuous-fixed.log保留该实验。

将同一采样规则写回探针，使用标准Event/Thread，finally先停止并回收采样
线程再销毁publisher。保持原扫描内容、图像尺寸、预览数值与等待期限，
不修改ObjectTrack、TF、算法、安全路由或1秒新鲜度检查。
正式第一次复验在并行Pyright负载下已通过no-target，但在观察者断开后的
angular.z=2.700预览等待超时；final-fixed-probe.log保留失败，不计为通过。
新tracker、无额外检查负载重跑同一完整探针：所有六组检查通过，退出码0；
fixed-clean-probe.log保留结果。资源负载下原短等待期限仍有时序限度，未
为使结果通过而放宽期限。正常固定输入行为与真实传感器14回合分别验证。

完整通过内容为：融合/Follow服务、无目标零预览、量程linear.x=0.119与
angular.z=-1.800、观察者断开后angular.z=2.700、待机停止、融合关闭/订阅
清理，以及dry_run=true且速度发布者0。随后重新安装robot_bringup并执行
安装版同一公开探针（ROS_DOMAIN_ID=185、从/tmp运行）：
`ros2 run robot_bringup tracking_control_acceptance_probe.py`，六组检查全部
通过，退出码0，证据installed-fixed-probe.log/installed-fixed-tracker.log。
最终两个验收Launch均正常退出，采样线程已回收，没有遗留验收进程。

### 包级检查与工具环境

源码外colcon test：robot_agent、robot_voice、robot_bringup、object_track、
ydlidar、usb_camera、img_decode、rknn_yolov6共8包任务完成，
`colcon test-result --verbose` 为 **30 tests，0 errors，0 failures，0 skipped**。
robot_agent的setuptools任务仍发现0项；它的实际行为由最终独立pytest96项执行。

第一次将整个旧工具venv加入colcon的PYTHONPATH，setuptools与系统
importlib_metadata版本冲突，虽测试结果成功，扩展加载报错，不计为干净
检查。只把pytest6.2.5及所需测试依赖放入源码外专用依赖目录后，colcon使用
系统setuptools45.2.0，8包重新检查无扩展错误，30项通过。未更改系统包，
未跳过ROS插件。colcon-test.log与colcon-test-clean.log均保留。

麦克风与可闻播放为可选项，本轮未启用；所有TTS保存音频可核查/试听。
本轮没有凭证、网络或provider阻塞的必验项。重启前的完整摘要含当前模拟与
接口确认限制，未将它们写成物理成功。所有构建与运行产物均在源码外。



## 审查修复

固定点为主线 `0bfb547`，使用 `git diff 0bfb547...HEAD`。
Standards初审发现证据mkdir/write_text失败会跳过ROS清理、掩盖原验收失败；
Spec初审0项。新增公开CLI回归：使用真实ROS无服务、外部时钟越过期限及
被普通文件占用的证据目录，首先因FileExistsError覆盖原AssertionError失败。
修复后仍显露原验收AssertionError，ROS上下文已关闭，单文件1 passed。

证据I/O只捕获OSError，失败时向stderr输出完整回执/计数及保存失败标记；
若已有验收异常，保留该异常；没有已有异常则保存错误继续抛出，不能计为
成功。外层finally始终销毁probe并shutdown；没有吞掉编程异常。
最终完整回归96 passed，Ruff39文件格式/静态检查与4个修改模块类型检查
通过。该处理依据本轮实际复现的文件写入失败，不增加推测性兜底。

### Standards

固定点 `0bfb547`，实现提交 `0d455bf` 与修复提交 `9e45cc5`。
复审 **0项剩余发现**。文件写入失败有实际证据，保留原异常、完整回执并
始终清理ROS；公开CLI回归验证实际生命周期。无可操作的设计异味。

### Spec

复审 **0项剩余发现**。14轮真实在线、安装版固定探针及源功能覆盖符合
#68/#54；没有以样例替代真实链路。保存失败不改写事实，也不记为成功。
并行负载时序限度、无真实人物目标及未启用麦克风/可闻播放均明确保留。

双轴总计：Standards 0项、Spec 0项；各轴均无未解决问题。
