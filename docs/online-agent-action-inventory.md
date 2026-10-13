# 旧 Online Agent 动作迁移清单

基准：旧仓库 `src/agent/main.py` → `llm.py` → `function_executor.py`。
包含 `_register_default_functions` 的全部条件注册动作，不依赖旧机器是否装有设备。
`go_to` 是 `navigate_to` 别名；`play_song` 转交 `play_music`。
旧执行器会把返回错误字符串的动作包装成 success=true，本迁移不沿用这一错误确认。
旧 LLM 按原始调用字符串同轮去重，跨轮清空；不同动作并发。
模拟头部方向动作更新状态，绝不访问 PWM。复杂头部动作及其原队列契约留待后续。
源参数解析存在混合引号参数丢失数字的问题，本迁移按字面值保留混合参数，禁止执行表达式。

| 源注册名/别名 | 参数及默认值 | 原行为 | #55 映射及后续计划 |
| --- | --- | --- | --- |
| `head_smile` | `无` | 微笑动作 | 已实现模拟；simulated=true |
| `head_nod` | `无` | 点头动作 | 已实现模拟；simulated=true |
| `head_shake` | `无` | 摇头动作 | 已实现模拟；simulated=true |
| `head_dance` | `无` | 跳舞动作 | 已实现模拟；simulated=true |
| `excited` | `无` | 兴奋表情 | 已实现模拟；simulated=true |
| `normal` | `无` | 正常表情 | 已实现模拟；simulated=true |
| `sleep` | `无` | 睡觉表情 | 已实现模拟；simulated=true |
| `wake_up` | `无` | 苏醒表情 | 已实现模拟；simulated=true |
| `volume_up` | `step=5` | 增加音量 | 已实现模拟；simulated=true |
| `volume_down` | `step=5` | 减少音量 | 已实现模拟；simulated=true |
| `volume_set` | `level=50` | 设置音量到指定级别 | 已实现模拟；simulated=true |
| `volume_mute` | `无` | 静音 | 已实现模拟；simulated=true |
| `volume_unmute` | `无` | 取消静音 | 已实现模拟；simulated=true |
| `volume_status` | `无` | 获取当前音量状态 | 已实现模拟；simulated=true |
| `head_forward` | `无` | 看向正前方 | 已实现模拟；simulated=true |
| `head_down` | `无` | 低头 | 已实现模拟；simulated=true |
| `head_up` | `无` | 仰头 | 已实现模拟；simulated=true |
| `head_left` | `无` | 向左看 | 已实现模拟；simulated=true |
| `head_right` | `无` | 向右看 | 已实现模拟；simulated=true |
| `head_reset` | `无` | 重置头部到中心位置 | 已实现模拟；simulated=true |
| `head_position` | `pitch=None, yaw=None` | 设置头部位置 | 未实现，not_implemented；后续模拟 Adapter |
| `show_wifi_info` | `无` | 显示WiFi信息 | 未实现，not_implemented；后续模拟 Adapter |
| `get_wifi_ip` | `无` | 获取WiFi IP地址 | 未实现，not_implemented；后续模拟 Adapter |
| `wifi_status` | `无` | 检查WiFi连接状态 | 未实现，not_implemented；后续模拟 Adapter |
| `play_music` | `song_name` | 播放音乐 | 已实现模拟；simulated=true |
| `play_song` | `song_name` | 播放歌曲（play_music的别名） | 已实现模拟；simulated=true |
| `stop_music` | `无` | 停止音乐播放 | 已实现模拟；simulated=true |
| `next_song` | `无` | 切到下一首歌 | 未实现，not_implemented；后续模拟 Adapter |
| `add_to_queue` | `song_name` | 添加歌曲到播放队列 | 未实现，not_implemented；后续模拟 Adapter |
| `music_status` | `无` | 获取音乐播放状态 | 已实现模拟；simulated=true |
| `recommend_songs` | `song_name=None` | 获取推荐歌曲 | 未实现，not_implemented；后续模拟 Adapter |
| `start_following` | `无` | 启动机器人跟随功能 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `stop_following` | `无` | 停止机器人跟随功能 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `toggle_following` | `无` | 切换机器人跟随功能状态 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `following_status` | `无` | 获取机器人跟随状态 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `enable_tracking` | `无` | 启用跟踪功能 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `disable_tracking` | `无` | 禁用跟踪功能 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `enable_lidar` | `无` | 启用激光雷达功能 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `disable_lidar` | `无` | 禁用激光雷达功能 | 未实现，not_implemented；后续接 ROS 2 感知/Follow 服务，dry_run=true |
| `navigate_to` | `location` | 导航到指定位置 | 未实现，not_implemented；后续模拟 Adapter |
| `go_to` | `location` | 导航到指定位置 | 未实现，not_implemented；后续模拟 Adapter |
| `cancel_navigation` | `无` | 取消当前导航任务 | 未实现，not_implemented；后续模拟 Adapter |
| `navigation_status` | `无` | 获取导航状态 | 未实现，not_implemented；后续模拟 Adapter |
| `list_locations` | `无` | 列出所有可用位置 | 未实现，not_implemented；后续模拟 Adapter |
| `add_location` | `name, x, y, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0` | 添加新位置 | 未实现，not_implemented；后续模拟 Adapter |
| `head_think` | `duration=2.0` | 思考动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_confused` | `duration=1.5` | 困惑动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_surprised` | `duration=1.0` | 惊讶动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_look_around` | `duration=3.0` | 环视动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_greet` | `duration=2.0` | 打招呼动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_goodbye` | `duration=1.5` | 告别动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_refuse` | `duration=1.0` | 拒绝动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_breathing` | `cycles=5, duration=0.5` | 呼吸动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_attention` | `direction="center", duration=1.0` | 注意力动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_emotional` | `emotion="happy", duration=3.0` | 情感表达动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_listen` | `duration=2.0` | 专注倾听动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_interest` | `duration=1.5` | 表示兴趣动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_concern` | `duration=2.0` | 表示关心动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_agree` | `duration=1.0` | 表示同意动作 | 未实现，not_implemented；后续模拟 Adapter |
| `head_disagree` | `duration=1.0` | 表示不同意动作 | 未实现，not_implemented；后续模拟 Adapter |
