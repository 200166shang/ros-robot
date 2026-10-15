"""纯文本会话规则：只拥有唤醒状态和活动期限。"""

import math
import re
from dataclasses import dataclass
from typing import Optional

WAKE_WORDS = tuple(
    name * 2 for name in ("小沫", "小莫", "小墨", "小末", "小陌", "小默")
)
SLEEP_COMMANDS = frozenset(
    (
        "休息",
        "睡觉",
        "晚安",
        "再见",
        "拜拜",
        "不聊了",
        "不说了",
        "我要休息",
        "我要睡觉",
        "我要走了",
        "先这样",
        "就这样",
        "好了",
        "够了",
        "结束对话",
        "停止对话",
        "我要去休息",
        "我要去睡觉",
        "我要去忙",
        "我要去工作",
        "休息一下",
        "睡一下",
        "小憩",
        "打盹",
        "午休",
        "夜宵",
    )
)
MUSIC_CONTROLS = (
    "关闭",
    "停止",
    "关掉音乐",
    "下一首",
    "切歌",
    "换歌",
    "跳过",
    "下一曲",
    "上一首",
    "上一曲",
    "前一首",
    "播放音乐",
    "开始播放",
    "继续播放",
    "恢复播放",
    "音量",
    "声音",
    "大小声",
    "静音",
)


@dataclass(frozen=True)
class SessionDecision:
    """本地会话结果；无决定表示交给 Agent。"""

    status: str
    reply: str


class VoiceSession:
    """仅根据文本、时间和音乐观察值决定会话状态。"""

    def __init__(self, silence_timeout: float = 120.0) -> None:
        """校验静音期限，初始处于待机。"""
        if not math.isfinite(silence_timeout) or silence_timeout <= 0:
            raise ValueError("超时必须为正有限秒数")
        self._silence_timeout = silence_timeout
        self._last_activity = 0.0
        self._awake = False

    @property
    def state(self) -> str:
        """返回会话状态，不读取时钟或外部能力。"""
        return "listening" if self._awake else "standby"

    def tick(self, now: float) -> None:
        """空闲时由应用推进静音期限。"""
        if now - self._last_activity >= self._silence_timeout:
            self._awake = False

    def mark_activity(self, now: float) -> None:
        """有效处理完成后延长当前会话活动期限。"""
        self._last_activity = now

    def decide(
        self, text: str, now: float, music_playing: bool
    ) -> Optional[SessionDecision]:
        """唤醒和休眠优先于音乐过滤，普通请求返回空决定。"""
        self.tick(now)
        clean = re.sub(r"[^\w]", "", text)
        if any(word in clean for word in WAKE_WORDS):
            self._awake = True
            self.mark_activity(now)
            return SessionDecision("woken", "我在，请说。")
        if not self._awake:
            return SessionDecision("ignored", "等待唤醒词。")
        if clean in SLEEP_COMMANDS:
            self._awake = False
            return SessionDecision("sleeping", "好的，进入待机。")
        if music_playing and not any(word in clean for word in MUSIC_CONTROLS):
            return SessionDecision("filtered", "音乐期间仅接收控制指令。")
        return None
