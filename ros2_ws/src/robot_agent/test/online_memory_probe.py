"""真实在线记忆验收，只报告阶段结果，不输出记忆内容。"""

import argparse
import json
import uuid
from pathlib import Path

from robot_agent.online_actions import ActionRegistry
from robot_agent.online_interaction import OnlineInteraction
from robot_agent.online_memory import ConversationMemory
from robot_agent.online_provider import DashScopeProvider


def main() -> None:
    """用专用外部记忆文件验证在线上下文、摘要、重启和清空。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--memory-file", required=True, type=Path)
    args = parser.parse_args()
    if args.memory_file.exists():
        parser.error("验收必须使用不存在的专用记忆文件，避免清空用户记忆")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    provider = DashScopeProvider(config)
    timeout = float(config.get("provider_timeout", 60))
    marker = "验收色号" + uuid.uuid4().hex[:12]

    def start() -> OnlineInteraction:
        """通过公开交互 Interface 重新加载同一专用文件。"""
        return OnlineInteraction(
            provider,
            ActionRegistry(),
            provider_timeout=timeout,
            memory=ConversationMemory(args.memory_file, 2, 2),
        )

    def submit(agent: OnlineInteraction, text: str) -> dict:
        """检查真实在线回合，不在异常报告中输出用户输入或回复。"""
        result = agent.submit(text)
        assert result["status"] == "completed", "在线回合未完成"
        assert not result["actions"], "验收不允许动作"
        assert not result["memory_warnings"], "记忆阶段存在故障"
        return result

    # 1. 两轮达到摘要阈值，第二轮必须使用近期上下文。
    agent = start()
    submit(agent, "只聊天，请记住我最喜欢的色号是：" + marker)
    result = submit(agent, "只聊天，我最喜欢的色号是什么？原样回答色号。")
    assert marker in result["reply"], "近期上下文未召回"
    assert args.memory_file.exists(), "持久摘要未生成"
    print("recent_context_and_summary: passed")

    # 2. 新交互实例只从摘要恢复事实，不共享旧实例的近期上下文。
    restarted = start()
    result = submit(restarted, "只聊天，我最喜欢的色号是什么？原样回答。")
    assert marker in result["reply"], "重启摘要未召回"
    print("restart_recall: passed")

    # 3. 清空覆盖两种记忆，并再次重启确认旧事实不再可见。
    assert restarted.clear_memory()["status"] == "completed", "清空失败"
    result = submit(start(), "只聊天，我最喜欢的色号是什么？不知道则说明。")
    assert marker not in result["reply"], "清空后仍召回旧记忆"
    print("clear_and_restart: passed; dry_run=true; no actions")


if __name__ == "__main__":
    main()
