# 在线模型与直接文本测试

正常运行只有麦克风入口：录音→在线ASR→文本→交互→在线TTS。
已删除独立ROS文本节点、online_agent可执行入口及text/clear_memory/
reconcile输入话题。文本只作为ASR输出或测试数据进入交互Interface。
旧离线前端依赖的文本话题不再提供，后续离线方案独立设计。

## 共同组装与配置

online_runtime.load_config读取外部UTF-8 JSON对象，支持路径中的~；
文件、JSON语法或顶层形状错误直接显露，不静默回退。
create_interaction集中创建模型、动作注册表和记忆；语音组装也调用它。
ROS参数声明、ASR/TTS、录音与播放仍由对应入口负责。

非敏感模型配置示例，追加到[完整配置](online-agent.md)：

```json
{
  "model": "qwen-plus",
  "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
  "api_key_env": "DASHSCOPE_API_KEY",
  "provider_timeout": 60,
  "action_timeout": 5
}
```

凭证仅从环境读取，不允许明文api_key。端点必须HTTPS，模型/端点
须与Key地域授权匹配；不会输出Key或HTTP错误正文。
provider_timeout/action_timeout单位秒，必须为正有限数。
语音识别与合成另用speech_timeout，配置见[语音说明](online-agent-voice.md)。

默认system prompt为随包安装的online_system_prompt.txt，保留旧人设、
动作目录及当前部署约束，不依赖运行目录。自定义时指定源码外
system_prompt_file；UTF-8文件为空或不存在时启动失败，不自动回退。

## 测试直接调用Interface

加载ROS及源码外安装环境，导入共同组装；不启动额外文本节点：

```python
from robot_agent.online_runtime import create_interaction, load_config

config = load_config("/absolute/external/test-config.json")
agent = create_interaction(config)
result = agent.submit("你好，请只聊天")
print(result)
# 独立测试可在每轮完整返回后调用：
# agent.clear_memory()
# agent.reconcile(result["turn_id"])
```

默认动作注册表为明确模拟；需要真实感知时运行[独立综合探针](online-agent.md)，
由其复用ROS感知组装，不恢复文本话题。测试需专用外部记忆路径，避免
污染日常对话。单一调用者逐项提交，不并发接入。

## 结果和恢复契约

submit返回turn_id、status、reply、actions；语音模块进一步补充
transcript、音频与会话状态后，由正常节点发布/online_agent/result。
交互状态为completed/failed/rejected/busy；动作保持原顺序和绑定参数，
状态为simulated_success/real_success/failed/unknown/not_executed。

模型接受function/response或fc/res；动作字符串只解析字面量参数，
不使用eval。完整动作列表先校验，全部有效后才顺序执行；失败停止余项，
有意重复不去重。动作回复只依据确认回执，不采用模型提前成功承诺。
完整动作与模拟范围见[业务清单](online-agent-inventory.md)。

模型等待超时不取消仍在途调用，其结束前拒绝新回合。动作unknown须用
原turn_id调用reconcile；迟到回执确认成功或失败后才能解除阻塞，不补执行
后续动作。迟到回执仍未知或异常时继续阻塞，需操作者核实设备后恢复。
正常麦克风没有文本控制入口，恢复规则见[语音说明](online-agent-voice.md)。

## 验证与历史

共同组装行为见test_online_runtime.py；正常ROS接线由
test_online_microphone_ros.py覆盖；网络适配器见test_online_provider.py。
测试不替代真实在线验收，最新范围和结果见[验收报告](online-agent-microphone-validation.md)。
最初文本节点的历史证据保留在[原文本验收](online-agent-text-validation.md)，
其中旧启动命令不再适用于当前实现。
