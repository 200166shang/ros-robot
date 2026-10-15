"""交互、动作和语音共用的回合结果快照契约。"""

from typing import Dict, List, Optional


def make_result(
    turn_id: str,
    status: str,
    reply: str,
    actions: Optional[List[Dict]] = None,
) -> Dict:
    """统一回合结构，返回记录快照，核对迟到回执不改写已发布结果。"""
    return {
        "turn_id": turn_id,
        "status": status,
        "reply": reply,
        "actions": [dict(action) for action in actions]
        if actions is not None
        else [],
    }
