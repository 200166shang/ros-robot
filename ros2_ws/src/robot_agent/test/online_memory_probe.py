"""真实在线记忆验收，只报告阶段结果，不输出记忆内容。"""

import argparse
import multiprocessing
import uuid
from pathlib import Path

from robot_agent.online_interaction import OnlineInteraction
from robot_agent.online_runtime import create_interaction, load_config


def verify_restart(config: dict, marker: str, cleared: bool) -> None:
    """在新进程重新构造 provider 和交互，仅从磁盘恢复记忆。"""
    agent = create_interaction(config)
    result = agent.submit("只聊天，我最喜欢的色号是什么？不知道则说明。")
    assert result["status"] == "completed", "重启在线回合未完成"
    assert not result["actions"], "验收不允许动作"
    assert not result["memory_warnings"], "重启记忆存在故障"
    if cleared:
        assert marker not in result["reply"], "清空后仍召回旧记忆"
    else:
        assert marker in result["reply"], "重启摘要未召回"
        assert agent.clear_memory()["status"] == "completed", "清空失败"


def main() -> None:
    """用专用外部记忆文件验证在线上下文、摘要、重启和清空。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--memory-file", required=True, type=Path)
    args = parser.parse_args()
    if args.memory_file.exists():
        parser.error("验收必须使用不存在的专用记忆文件，避免清空用户记忆")
    config = dict(
        load_config(args.config),
        memory_file=str(args.memory_file),
        memory_recent_turns=2,
        memory_summary_trigger=2,
    )
    # 色号只含随机标识，避免模型把中文字段标签当成可省略的说明。
    marker = uuid.uuid4().hex[:12]

    def start() -> OnlineInteraction:
        """通过公开交互 Interface 重新加载同一专用文件。"""
        return create_interaction(config)

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

    # 2. spawn 独立进程，避免继承旧交互实例或内存上下文。
    context = multiprocessing.get_context("spawn")
    restarted = context.Process(
        target=verify_restart,
        args=(config, marker, False),
    )
    restarted.start()
    restarted.join()
    assert restarted.exitcode == 0, "独立进程重启召回或清空失败"
    print("process_restart_recall: passed")

    # 3. 再次独立启动，验证清空的持久效果，不输出原始回复。
    cleared = context.Process(
        target=verify_restart,
        args=(config, marker, True),
    )
    cleared.start()
    cleared.join()
    assert cleared.exitcode == 0, "清空后的独立进程验收失败"
    print("clear_and_process_restart: passed; no actions")


if __name__ == "__main__":
    main()
