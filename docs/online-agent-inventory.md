# Online Agent 源业务与动作清单

源代码取自本机旧 ROS 1 checkout `robot/src/agent`，不是现有本地 Qwen 桥接。源版本 `22cd28d2d63ba1165f3fbceba205e02ed94f204d`。
动作来源 `function_executor.py::_register_default_functions`，包括条件注册能力，不因 SDK 或硬件缺失而删行。
下表参数保留原默认值和别名。当前 #64 完整模拟52项动作及别名；其余8项感知动作由 #65 接入，仍明确整表拒绝。

| 动作 | 原参数与默认值 | 别名目标 | 源行为 | 源函数/行 | 当前状态及归属 |
|---|---|---|---|---|---|
| `head_smile` | `无` | — | 微笑动作 | `_head_smile` L492 | #63 代表模拟；#64 完整状态模拟 |
| `head_nod` | `无` | — | 点头动作 | `_head_nod` L500 | #63 代表模拟；#64 完整状态模拟 |
| `head_shake` | `无` | — | 摇头动作 | `_head_shake` L506 | #63 代表模拟；#64 完整状态模拟 |
| `head_dance` | `无` | — | 跳舞动作 | `_head_dance` L512 | #64 完整状态模拟 |
| `excited` | `无` | — | 兴奋表情 | `_excited` L520 | #64 完整状态模拟 |
| `normal` | `无` | — | 正常表情 | `_normal` L526 | #64 完整状态模拟 |
| `sleep` | `无` | — | 睡觉表情 | `_sleep` L532 | #64 完整状态模拟 |
| `wake_up` | `无` | — | 苏醒表情 | `_wake_up` L538 | #64 完整状态模拟 |
| `volume_up` | `step=5` | — | 增加音量 | `_volume_up` L705 | #64 完整状态模拟 |
| `volume_down` | `step=5` | — | 减少音量 | `_volume_down` L720 | #64 完整状态模拟 |
| `volume_set` | `level=50` | — | 设置音量到指定级别 | `_volume_set` L735 | #64 完整状态模拟 |
| `volume_mute` | `无` | — | 静音 | `_volume_mute` L752 | #64 完整状态模拟 |
| `volume_unmute` | `无` | — | 取消静音 | `_volume_unmute` L767 | #64 完整状态模拟 |
| `volume_status` | `无` | — | 获取当前音量状态 | `_volume_status` L782 | #64 完整状态模拟 |
| `head_forward` | `无` | — | 看向正前方 | `_head_forward` L545 | #64 完整状态模拟 |
| `head_down` | `无` | — | 低头 | `_head_down` L550 | #64 完整状态模拟 |
| `head_up` | `无` | — | 仰头 | `_head_up` L555 | #64 完整状态模拟 |
| `head_left` | `无` | — | 向左看 | `_head_left` L560 | #64 完整状态模拟 |
| `head_right` | `无` | — | 向右看 | `_head_right` L565 | #64 完整状态模拟 |
| `head_reset` | `无` | — | 重置头部到中心位置 | `_head_reset` L570 | #64 完整状态模拟 |
| `head_position` | `pitch=None, yaw=None` | — | 设置头部位置 | `_head_position` L575 | #64 完整状态模拟 |
| `show_wifi_info` | `无` | — | 显示WiFi信息 | `_show_wifi_info` L587 | #64 完整状态模拟 |
| `get_wifi_ip` | `无` | — | 获取WiFi IP地址 | `_get_wifi_ip` L599 | #64 完整状态模拟 |
| `wifi_status` | `无` | — | 检查WiFi连接状态 | `_wifi_status` L613 | #64 完整状态模拟 |
| `play_music` | `song_name` | — | 播放音乐 | `_play_music` L811 | #64 完整状态模拟 |
| `play_song` | `song_name` | play_music | 播放歌曲（play_music的别名） | `_play_song` L831 | #64 完整状态模拟 |
| `stop_music` | `无` | — | 停止音乐播放 | `_stop_music` L835 | #64 完整状态模拟 |
| `next_song` | `无` | — | 切到下一首歌 | `_next_song` L856 | #64 完整状态模拟 |
| `add_to_queue` | `song_name` | — | 添加歌曲到播放队列 | `_add_to_queue` L874 | #64 完整状态模拟 |
| `music_status` | `无` | — | 获取音乐播放状态 | `_music_status` L886 | #64 完整状态模拟 |
| `recommend_songs` | `song_name=None` | — | 获取推荐歌曲 | `_recommend_songs` L903 | #64 完整状态模拟 |
| `start_following` | `无` | — | 启动机器人跟随功能 | `_start_following` L919 | 本票整表拒绝；#65 |
| `stop_following` | `无` | — | 停止机器人跟随功能 | `_stop_following` L933 | 本票整表拒绝；#65 |
| `toggle_following` | `无` | — | 切换机器人跟随功能状态 | `_toggle_following` L947 | 本票整表拒绝；#65 |
| `following_status` | `无` | — | 获取机器人跟随状态 | `_following_status` L961 | 本票整表拒绝；#65 |
| `enable_tracking` | `无` | — | 启用跟踪功能 | `_enable_tracking` L975 | 本票整表拒绝；#65 |
| `disable_tracking` | `无` | — | 禁用跟踪功能 | `_disable_tracking` L989 | 本票整表拒绝；#65 |
| `enable_lidar` | `无` | — | 启用激光雷达功能 | `_enable_lidar` L1003 | 本票整表拒绝；#65 |
| `disable_lidar` | `无` | — | 禁用激光雷达功能 | `_disable_lidar` L1017 | 本票整表拒绝；#65 |
| `navigate_to` | `location` | — | 导航到指定位置 | `_navigate_to` L1032 | #64 完整状态模拟 |
| `go_to` | `location` | navigate_to | 导航到指定位置 | `_navigate_to` L1032 | #64 完整状态模拟 |
| `cancel_navigation` | `无` | — | 取消当前导航任务 | `_cancel_navigation` L1051 | #64 完整状态模拟 |
| `navigation_status` | `无` | — | 获取导航状态 | `_navigation_status` L1065 | #64 完整状态模拟 |
| `list_locations` | `无` | — | 列出所有可用位置 | `_list_locations` L1084 | #64 完整状态模拟 |
| `add_location` | `name, x, y, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0` | — | 添加新位置 | `_add_location` L1099 | #64 完整状态模拟 |
| `head_think` | `duration=2.0` | — | 思考动作 | `_head_think` L628 | #64 完整状态模拟 |
| `head_confused` | `duration=1.5` | — | 困惑动作 | `_head_confused` L633 | #64 完整状态模拟 |
| `head_surprised` | `duration=1.0` | — | 惊讶动作 | `_head_surprised` L638 | #64 完整状态模拟 |
| `head_look_around` | `duration=3.0` | — | 环视动作 | `_head_look_around` L643 | #64 完整状态模拟 |
| `head_greet` | `duration=2.0` | — | 打招呼动作 | `_head_greet` L648 | #64 完整状态模拟 |
| `head_goodbye` | `duration=1.5` | — | 告别动作 | `_head_goodbye` L653 | #64 完整状态模拟 |
| `head_refuse` | `duration=1.0` | — | 拒绝动作 | `_head_refuse` L658 | #64 完整状态模拟 |
| `head_breathing` | `cycles=5, duration=0.5` | — | 呼吸动作 | `_head_breathing` L663 | #64 完整状态模拟 |
| `head_attention` | `direction="center", duration=1.0` | — | 注意力动作 | `_head_attention` L668 | #64 完整状态模拟 |
| `head_emotional` | `emotion="happy", duration=3.0` | — | 情感表达动作 | `_head_emotional` L673 | #64 完整状态模拟 |
| `head_listen` | `duration=2.0` | — | 专注倾听动作 | `_head_listen` L679 | #64 完整状态模拟 |
| `head_interest` | `duration=1.5` | — | 表示兴趣动作 | `_head_interest` L684 | #64 完整状态模拟 |
| `head_concern` | `duration=2.0` | — | 表示关心动作 | `_head_concern` L689 | #64 完整状态模拟 |
| `head_agree` | `duration=1.0` | — | 表示同意动作 | `_head_agree` L694 | #64 完整状态模拟 |
| `head_disagree` | `duration=1.0` | — | 表示不同意动作 | `_head_disagree` L699 | #64 完整状态模拟 |

## 状态与依赖

- 表情/LCD：`emoji.py`、`lcd.py`，显示命令及动画线程；旧 head_nod/head_dance 实际显示兴奋而非舵机点头/舞蹈。#64 完整模拟显示状态。
- 头部：`head_servo_controller.py`、`servo_controller_pwm.py`，pitch/yaw 当前角度和动作队列；#64 模拟角度与动作状态。源 pitch 为度、限 65–120，yaw 为度、限 50–130；后续实现需明确校验，不能照搬队列接受即成功。
- 音量：系统 amixer，音量/静音；#64 模拟，禁止改系统音量。level 旧实现限制 0–100。
- 音乐：`cloud_music.py`，播放状态、当前歌曲、队列、推荐与 ASR music_playing；#64 模拟，不播放或拉取歌曲。
- WiFi：LCD 显示、主机 IP/连接状态，#64 模拟，不修改网络。
- 导航：`navigation_controller.py`，已注册位置、导航目标/活动/取消与 ROS action 状态；#64 模拟，保留位置参数（map 米、单位四元数）。
- 跟随：`robot_following_controller.py`，tracking_enabled/lidar_enabled/following_active；#65 接入现有 ROS 2 固定组合、融合与 Follow 服务，保持 dry_run。
- 相机：旧在线主入口未直接注册相机函数，Follow 依赖链启动相机/目标检测。现有本地桥接另有 start_receiving_image、stop_camera_collection、query_camera_status、query_person_tracking_status、start_tracking；本地桥接现已按用户决定弃用，#65 统一 Online Agent 的真实接入。

## 主入口业务迁移

| 业务 | 源入口/状态 | 已确认改进 | 归属 |
|---|---|---|---|
| 初始化/退出、配置、信号与资源清理 | main.py、config_manager.py、start_agent.sh | 凭证与产物外置，薄 ROS 入口 | #63 文本入口；#68 综合启动 |
| 在线推理/结构化输出 | llm.py LLMAgent、function/response、OpenAI DashScope SSE | 收齐片段后整表校验、按序执行、保留重复、单回合忙拒绝 | #63 |
| 动作执行/结果回复 | function_executor.py 异步线程与头部队列，llm.py 同轮 set 去重、边解析边 TTS | 不再并发或去重，不提前成功；失败/超时停止，已发出超时未知，不回滚/重试 | #63 |
| 唤醒/连续会话/待机 | asr.py wake_word_detected、120秒 silence_timeout；小沫/小莫/小墨/小末/小陌/小默各重复两次 | 明确休眠指令匹配，避免子串误触发 | #67 |
| 在线语音识别/重连 | asr.py Recognition、连接与监听线程、pause_audio/resume_audio | WAV 单回合可跳过唤醒；真实 ASR 验收 | #67 |
| 在线 TTS/播放/恢复采集 | llm.py Callback、CosyVoice、重试/连续失败禁用 | 动作确认后才合成；保留可试听音频，播放可选 | #67 |
| 音乐输入过滤 | asr.py music_playing、控制关键词过滤 | 保留音乐过滤与回合后恢复采集 | #64/#67 |
| 长短期记忆、摘要、保存 | llm.py load/save/summarize_memory、后台摘要 | 持久摘要+有界近期上下文，清空，保存失败不阻断 | #66 |
| 搜索依赖 | search_engine.py 未被在线主入口/动作表引用 | 不新增不存在的搜索动作 | 清单记录，无新增票 |
| 真实录音与在线综合验收 | ASR→LLM→动作→TTS | 必须真实在线，阻塞明确报告 | #67/#68 |

#63 交付三项代表表情及顺序执行主链路；#64 补齐52项模拟动作与别名。#65 感知动作仍待真实接入。当前状态语义、源实现差异及独立演示见 [完整模拟说明](online-agent-simulation.md)。

## 底盘与提示音核对（#64）

- 旧 `robot_following_controller.py` 经跟随控制栈使用底盘；没有额外直行/转弯/速度动作注册。8项跟随/tracking/LiDAR属于 #65，不能在本票以模拟成功替代真实感知接口。导航模拟不创建 action client 或发布 `/cmd_vel`。
- 旧 `main.py::play_startup_sound/play_error_sound` 调用 ffplay 播放启动/错误提示音，不是模型注册动作。新 ROS 入口启动和失败回执仅记录 `simulate_cue(startup/error)`，不启动播放器、不生成音频。唤醒/语音生命周期的提示音由 #67 复用，未发明新的模型动作。
- LCD 显示状态包括兴奋、正常、good_night、苏醒、wifi_info；音乐播放/切歌设兴奋，停止设正常，保留源跨能力状态。
