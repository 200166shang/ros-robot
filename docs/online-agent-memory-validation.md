# #66 在线会话记忆验收

日期：2026-10-14（北京时间）。实施 worktree：`/home/orangepi/code/ros-robot-issue-66`，分支：`codex/issue-66-online-memory`；实施前已 fetch 最新主线，基线 `1e2929f93c2721675f912e74f4f33d0aca12af8f`（#70，#63 已关闭）。原 checkout 未改动。

## 已通过

- TDD 首个交互/重启/清空测试在实现前因缺少 `online_memory` 失败，实现后通过。按父规格约定的公开交互 Interface 测试，不访问私有方法或状态。
- 新增 8 项固定行为测试：连续上下文、摘要后重启召回、持久及近期清空、摘要失败有界上下文、保存/清空失败反馈、损坏文件脱敏反馈、摘要超时忙拒绝/安全清空、摘要动作零执行，以及真实 ROS 话题文本/清空接入。ROS 测试仅 HTTPS 出口使用固定响应，不计作真实云端验收。
- 完整 Python 回归 **44 passed**，Ruff 0.9.10 check 与 format --check 通过，Pyright 1.1.390（Python 3.8）对在线交互、记忆、ROS 入口与真实验收脚本通过。
- ROS 2 Foxy、Python 3.8.10：robot_agent colcon 构建通过，build/install/log 均在源码外 `/tmp/ros-robot-66-*`。无真实设备输出；入口要求 dry_run=true。

复现命令（在 worktree）：

```bash
source /opt/ros/foxy/setup.bash
export PYTHONPATH="$PWD/ros2_ws/src/robot_agent:$PWD/ros2_ws/src/robot_voice:$PYTHONPATH"
python3 -m pytest -q tests ros2_ws/src/robot_agent/test \
  ros2_ws/src/robot_voice/test ros2_ws/src/robot_bringup/test
ruff check .
ruff format --check .
pyright --pythonversion 3.8 \
  ros2_ws/src/robot_agent/robot_agent/online_memory.py \
  ros2_ws/src/robot_agent/robot_agent/online_interaction.py \
  ros2_ws/src/robot_agent/robot_agent/online_ros_node.py \
  ros2_ws/src/robot_agent/test/online_memory_probe.py
colcon --log-base /tmp/ros-robot-66-log build \
  --base-paths ros2_ws/src/robot_agent \
  --build-base /tmp/ros-robot-66-build \
  --install-base /tmp/ros-robot-66-install --packages-select robot_agent
```

本机 Pyright 的原缓存缺少完整 typeshed，第一次运行出现内置类型缺失；使用源码外现有完整 typeshed (`--typeshedpath /tmp/ros-robot-55-typecheck/mypy/typeshed`) 后检查通过。没有为工具缺失修改产品逻辑。

## 双轴审查

按 code-review 技能以固定主线基线审查两轴，互相独立。

### Standards

**0 项明确问题**。中文 docstring、公共 Interface、主流程和记忆职责集中符合仓库规范，未发现需报告的 baseline smell。人工检查多阶段编号、语义空行与 ROS/在线 Adapter 职责。

原 checkout 的 ADR 0007 不在此次最新主线 worktree 中，审查未将其视作已存在的主线文件；记忆与交互设计遵循 #54/#66 的同一约定，没有修改或提交原 checkout 的领域文档。

### Spec

首次审查发现 **1 项未满足验收**：当时未提供凭证，真实云端记忆链路尚未运行。其后用户提供源码外 CSV 凭证，真实云端与独立进程重启复验全部通过，补足该项；其他实现和固定行为未发现缺失、额外范围或错误。最终重新执行两个独立审查，Standards **0 项**、Spec **0 项**。

## 真实云端已通过

起初当前进程没有 `DASHSCOPE_API_KEY`，默认外部配置也不存在，未将固定响应计作在线通过。用户随后明确提供源码外 CSV 凭证文件；仅在验收进程内解析唯一 API Key 并注入环境，未输出原始文件、凭证或 HTTP 错误，未提交该文件。

真实 DashScope qwen-plus、北京兼容 HTTPS 端点、provider_timeout=60 秒；仅该验收进程对 dashscope.aliyuncs.com 使用 NO_PROXY，不修改全局代理。配置和专用合成记忆在源码外临时目录，运行结束自动清理。脚本不执行动作，也无真实设备 Adapter，入口继续要求 dry_run=true。

- 第一次真实云端运行：连续文本召回、真实在线摘要生成、重新加载摘要召回及清空后重新加载均通过。
- 随后将验收脚本的重启升级为 spawn 独立进程：新进程自行构造真实 provider/交互，从磁盘摘要恢复，不继承旧交互实例；另一新进程验证清空后的持久效果。
- 最终真实云端运行退出码 **0**，仅输出以下脱敏阶段结论：

```text
recent_context_and_summary: passed
process_restart_recall: passed
clear_and_process_restart: passed; dry_run=true; no actions
```

上述证据来自真实在线调用，不是固定 provider。验收使用随机合成事实，报告不记录输入、回复或摘要内容，不保存录音或凭证。可按 [脱敏复验步骤](online-agent-memory.md) 运行 `test/online_memory_probe.py` 重现。没有剩余已知未满足验收项。
