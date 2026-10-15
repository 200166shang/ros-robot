# 完整缺失设备模拟（#64）

`ActionRegistry()` 默认组装52项源模拟动作及别名，无需任何设备、播放器、联网音乐服务或系统命令。动作名称和默认值见 [源动作清单](online-agent-inventory.md)。8项跟随/tracking/LiDAR动作等待 #65 的真实感知接入，仍整表拒绝。

## 独立演示

Python 3.8 起，不依赖 ROS 或云端 Key：

```bash
PYTHONPATH=ros2_ws/src/robot_agent python3 -m robot_agent.actions.demo
```

安装 `robot_agent` 后也可在源码目录外运行相同模块，无需设置源码 PYTHONPATH。演示采用固定模型响应，提交 `OnlineInteraction.submit(text)`，输出输入、回合标识、可信回复、绑定参数和每步动作结果。顺序展示头部、重复呼吸、位置注册/导航/取消、音乐队列/推荐/停止、音量/静音/WiFi及未知导航目标失败停止。启动/错误提示音只记录模拟回执。

这不是云端模型或在线语音验收。真实在线启动和话题命令沿用 [文本入口](online-agent-text.md)，始终指定 `dry_run=true`。例如先监听 `/online_agent/result`，再提交“注册书房为地图坐标1、2，导航到书房，查询状态，然后取消导航”。默认模型提示词包含全部模拟名称、参数与限制；自定义提示词需自行同步。

## 状态和结果

每项动作 `data` 为独立状态快照，后续动作不改写历史结果；`detail` 包含明确模拟描述和查询值，确认后的 `reply` 同时报告结果及说明。结果为 `simulated_success` 表示模拟状态转换完成，不代表真实设备运动或播放。

| 能力 | 状态与行为 |
|---|---|
| 头部/LCD | 初始pitch/yaw均为90度、LCD正常。部分轴更新保留另一轴；pitch范围65–120、yaw范围50–130。组合轨迹在data.steps逐步展开，保留重复。 |
| 导航 | 每个Agent初始只有源厨房位置。add_location新增或替换位置；navigate_to/go_to从idle/cancelled进入active，取消进入cancelled。活动任务不能被新目标覆盖；必须先取消。未知目标明确failed，后项not_executed。模拟不自动到达。 |
| 音乐 | 当前歌曲、FIFO队列、is_playing。play_song等价play_music；队列保留重复。next_song优先队列，否则使用源静态推荐表首首歌曲；停止保留歌曲和队列。播放/切歌同步LCD兴奋，停止同步正常。 |
| 音量 | 初始50、未静音。up/down非负步长，结果0–100饱和；set保留旧整数转换与饱和。静音不丢失音量。 |
| WiFi | 固定模拟connected=true、ssid=simulated-network、ip=192.0.2.2。show_wifi_info设置LCD为wifi_info；查询不读取主机真实网络。 |
| 提示音 | ROS入口启动和failed回执记录startup/error提示音，不运行ffplay或生成音频。 |

注册表公开的 `music.is_playing` 和 `music_status` 回执提供 #67 会话输入过滤所需状态；本票没有新增语音输入过滤流程。各能力的状态按实例独立，无全局位置表、音乐控制器或无限历史列表。

## 输入和顺序契约

完整动作列表先校验动作名称、调用签名和参数，任一无效则零执行。只校验输入格式和几何值，不在校验阶段改变状态或检查尚未执行的注册结果，所以同轮 `add_location→navigate_to` 可运行。位置存在性及导航活动冲突在执行阶段判断，失败停止后项。

名称必须为非空文本，数值必须有限且不是布尔值。位置使用map米、单位四元数，允许源坐标舍入误差0.001。无效方向、情感、空位置/歌曲、不合法角度及非正duration均拒绝。`head_breathing` cycles要求1–64整数，限制不可信输入的展开资源；默认仍为5。

头部duration使用虚拟秒，不真实等待。组合动作按源姿态顺序展开，将请求duration均分到各步；呼吸总duration为cycles×duration。修正旧动作忽略duration或实际超时长的问题，不复刻线程队列、真实舵机平滑插值及时间循环。think显示一个含顿悟的完整模拟周期，confused显示一个左右摆动周期；duration改变虚拟时间，不改变重复次数。所需多次动作通过列表有意重复表达。

保留旧LCD映射：head_smile/head_nod/head_dance/excited显示兴奋，head_shake/normal显示正常，sleep显示good_night，wake_up显示苏醒。旧这些注册动作没有舵机点头或跳舞，不添加未经约定的物理含义。音乐和WiFi共享同一LCD状态。

真实底盘驱动、ROS navigation action client、PWM、LCD驱动、系统音量/网络修改及音乐/提示音播放均不进入模拟Implementation。没有额外发明底盘或提示音模型动作。真实ASR/LLM/TTS、记忆和综合验收仍归属后续票。

## 能力表与统一加载

各能力在实现旁边提供动作表：`head_actions`、`navigation_actions`、`music_actions`、`volume_actions`、`wifi_actions`。表的形式统一为`Dict[str, ActionHandler]`，处理器同时持有执行函数和可选参数校验函数。别名引用同一处理器，状态继续由绑定的模拟对象持有。

注册表的初始化只组装状态对象并加载能力表，例如：

```python
self.register_many(head_actions(self.head))
self.register_many(navigation_actions(self.navigation))
self.register_many(music_actions(self.music))
self.register_many(volume_actions(self.volume))
self.register_many(wifi_actions(self.head.expression))
```

`register_many`统一合并能力表，同名覆盖沿用`register`的配置阶段语义。已有`register/validate/execute`和默认52项动作保持兼容。共享`ActionHandler`放在`actions/contracts.py`，能力定义不依赖注册表实现；`ActionHandler`从`robot_agent.actions.contracts`导入。

本次先完成能力定义与注册机制的分离。尚未新增外部配置、动态导入或自动发现，全部能力默认可用；部署能力选择与别名配置可在确有需求时基于同一能力表接入。
