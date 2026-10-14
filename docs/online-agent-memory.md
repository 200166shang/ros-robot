# 在线会话记忆（#66）

记忆职责集中在 `ConversationMemory`。交互先收齐回复并确认动作结果，再更新记忆；provider 仍使用 `complete(text, timeout)`，上下文作为带明确标记的 JSON 用户数据提供，不覆盖系统规则。摘要复用真实在线 provider 的 function/response 契约，只接受无动作的文字回复，不执行摘要里的动作。只收录交互实际回复，不收录模型的执行前成功承诺。

## 配置及存储

在源码外的在线配置中加入：

```json
{
  "memory_file": "/home/orangepi/.local/state/ros-robot/conversation-summary.json",
  "memory_recent_turns": 6,
  "memory_summary_trigger": 6
}
```

这也是 ROS 入口的默认配置。要求两个回合数是整数，`1 <= memory_summary_trigger <= memory_recent_turns <= 32`。近期上下文按完整输入/实际回复计回合，达到阈值后，将已有摘要与近期上下文合并为最多 4096 字符的摘要。摘要成功后清空已纳入摘要的近期上下文，失败时保留最近的有限回合，后续回合重新尝试摘要；超出上限的旧回合被移除。每次摘要都会合并上一次摘要。近期上下文不跨重启保存；跨重启仅恢复摘要。

路径支持 `~`，不允许落在 Git 源码仓库内（包括 worktree）。摘要文件采用版本化 JSON、私有临时文件、原子替换，文件权限为 0600，新建末级目录为 0700；不包含凭证、录音或完整逐轮历史。只有成功生成摘要才保存，尚未达到阈值的近期回合不会跨重启恢复。重启时缺失文件正常启动；文件损坏、过大或读取失败不阻断启动，首个记忆更新回执报告 `load_failed`。

`OnlineInteraction` 的非 ROS 调用方可注入 `memory=ConversationMemory(...)`；未注入时保留原有无记忆行为。

## 清空与故障反馈

`OnlineInteraction.clear_memory()` 清空近期上下文及内存摘要，并原子保存空摘要。ROS 入口：

```bash
ros2 topic pub --once /online_agent/clear_memory std_msgs/msg/String '{data: "clear"}'
```

同一 `/online_agent/result` 返回关联 turn_id、status、reply 和 `memory_warnings`。回合或摘要请求在途时返回 busy，请在其结束后重新请求清空。摘要超时不取消外部调用，其结束前新回合也返回 busy；迟到摘要可能保存，但不能与成功清空重叠。

已确定回复保持其状态和动作事实，记忆错误放在脱敏 `memory_warnings` 中：`summary_failed`、`summary_timeout`、`save_failed`、`load_failed`。不输出原始 provider 错误或记忆内容。摘要/保存的等待使用 provider_timeout；底层磁盘写入不支持取消，因此在途写入也保持 busy。

保存失败时内存摘要仍可供后续使用，但本次摘要不保证跨重启恢复；下一次成功摘要时再次保存。清空保存失败返回 failed 和 `clear_save_failed`，本进程内存已清空，磁盘旧摘要可能在重启后恢复，必须重新清空成功后再依赖重启效果。没有把失败清空伪报为持久成功。

## 脱敏复验

启动继续保持 `dry_run=true`。按照 [在线文本启动](online-agent-text.md) 配置真实云端凭证。使用不存在的源码外专用验收文件，不使用用户现有记忆：

```bash
PYTHONPATH="ros2_ws/src/robot_agent:$PYTHONPATH" \
  python3 ros2_ws/src/robot_agent/test/online_memory_probe.py \
  --config "$HOME/.config/ros-robot/online.json" \
  --memory-file "$HOME/.local/state/ros-robot/memory-66-validation.json"
```

脚本通过真实 DashScope、公开交互 Interface 连续提交文本，验证近期召回、摘要生成、独立进程重启召回、清空后再次独立进程重启；不执行任何动作，只打印阶段通过信息，不打印输入、摘要或回复。模型事实保留失败会如实使断言失败，不以固定 provider 替代真实通过。验收文件含专用合成事实，仍保留在源码外。

固定行为检查：

```bash
PYTHONPATH="ros2_ws/src/robot_agent:$PYTHONPATH" \
  python3 -m pytest -q ros2_ws/src/robot_agent/test/test_online_memory.py
```

本次固定测试、构建与真实云端证据见 [验收记录](online-agent-memory-validation.md)。
