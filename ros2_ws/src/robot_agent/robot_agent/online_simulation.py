"""缺失设备的状态模拟：只更新内存与日志，绝不连接硬件或修改系统。"""

import logging
import math
from copy import deepcopy
from functools import partial
from typing import Any, Callable, Dict, List, Optional

from .online_action_contracts import ActionHandler

LOGGER = logging.getLogger(__name__)


def simulated(detail: str, **data: Any) -> Dict:
    """返回独立的模拟快照，日志不含外部凭证或系统信息。"""
    LOGGER.info("dry_run=true %s", detail)
    return {
        "status": "simulated_success",
        "detail": "模拟：" + detail,
        "data": deepcopy(data),
    }


def validate_number(value: float, name: str) -> None:
    """在动作输入处拒绝布尔值、非数字及非有限值。"""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(name + " 必须是有限数字")


def validate_text(value: str) -> None:
    """名称参数必须为非空文本；长度受动作输入上限约束。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("名称必须为非空文本")


def validate_location(location: str) -> None:
    """只验证目标名称格式，位置存在性在按序执行时判定。"""
    validate_text(location)


def validate_pose(
    name: str,
    x: float,
    y: float,
    z: float = 0.0,
    qx: float = 0.0,
    qy: float = 0.0,
    qz: float = 0.0,
    qw: float = 1.0,
) -> None:
    """位置使用 map 米及单位四元数，拒绝无效几何参数。"""
    validate_text(name)
    for field, value in zip(
        ("x", "y", "z", "qx", "qy", "qz", "qw"),
        (x, y, z, qx, qy, qz, qw),
    ):
        validate_number(value, field)
    norm = math.hypot(qx, qy, qz, qw)
    if not math.isclose(norm, 1.0, abs_tol=0.001):
        raise ValueError("姿态必须为单位四元数")


class NavigationSimulation:
    """集中管理注册位置和导航任务；活动任务只由显式取消结束。"""

    def __init__(self) -> None:
        """复制源厨房坐标，每个 Agent 独立维护位置与任务。"""
        self.locations = {
            "厨房": dict(
                x=2.491, y=-0.331, z=0.0, qx=0.0, qy=0.0, qz=-0.389, qw=0.921
            ),
        }
        self.current_goal: Optional[str] = None
        self.state = "idle"

    def add_location(
        self,
        name: str,
        x: float,
        y: float,
        z: float = 0.0,
        qx: float = 0.0,
        qy: float = 0.0,
        qz: float = 0.0,
        qw: float = 1.0,
    ) -> Dict:
        """注册或替换位置，不发出地图或设备调用。"""
        self.locations[name] = dict(x=x, y=y, z=z, qx=qx, qy=qy, qz=qz, qw=qw)
        return simulated("注册位置 " + name, locations=self.locations)

    def list_locations(self) -> Dict:
        """返回全部已注册位置的快照。"""
        return simulated("位置列表", locations=self.locations)

    def navigate_to(self, location: str) -> Dict:
        """模拟提交目标；未知目标或已有活动任务明确失败。"""
        if location not in self.locations:
            return {"status": "failed", "detail": "模拟：未知位置 " + location}
        if self.state == "active":
            return {"status": "failed", "detail": "模拟：请先取消当前导航"}
        self.current_goal = location
        self.state = "active"
        return self.navigation_status()

    def cancel_navigation(self) -> Dict:
        """取消活动目标；无活动目标时保持状态，可重复查询和取消。"""
        if self.state == "active":
            self.state = "cancelled"
        return self.navigation_status()

    def navigation_status(self) -> Dict:
        """报告模拟任务状态，活动状态不宣称已到达目标。"""
        return simulated(
            f"导航 {self.state}，目标 {self.current_goal}",
            state=self.state,
            is_navigating=self.state == "active",
            current_goal=self.current_goal,
        )


def navigation_actions(
    navigation: NavigationSimulation,
) -> Dict[str, ActionHandler]:
    """导航动作与校验在本能力旁定义，别名共享同一个处理器。"""
    navigate = ActionHandler(navigation.navigate_to, validate_location)
    return {
        "navigate_to": navigate,
        "go_to": navigate,
        "add_location": ActionHandler(navigation.add_location, validate_pose),
        "cancel_navigation": ActionHandler(navigation.cancel_navigation),
        "navigation_status": ActionHandler(navigation.navigation_status),
        "list_locations": ActionHandler(navigation.list_locations),
    }


RECOMMENDATIONS = {
    "小幸运": ["青花瓷", "稻香", "夜曲", "告白气球"],
    "青花瓷": ["小幸运", "稻香", "夜曲", "东风破"],
    "稻香": ["小幸运", "青花瓷", "夜曲", "听妈妈的话"],
    "夜曲": ["小幸运", "青花瓷", "稻香", "七里香"],
    "告白气球": ["小幸运", "青花瓷", "稻香", "等你下课"],
    "东风破": ["青花瓷", "小幸运", "稻香", "夜曲"],
    "七里香": ["夜曲", "小幸运", "青花瓷", "稻香"],
    "听妈妈的话": ["稻香", "小幸运", "青花瓷", "夜曲"],
    "等你下课": ["告白气球", "小幸运", "青花瓷", "稻香"],
}


def validate_song(song_name: str) -> None:
    """播放和队列仅接受非空歌曲名。"""
    validate_text(song_name)


def validate_recommendation(song_name: Optional[str] = None) -> None:
    """推荐参数允许省略，但不能提供空文本。"""
    if song_name is not None:
        validate_text(song_name)


class MusicSimulation:
    """歌曲、队列和播放状态共同归属音乐模拟，不启动播放器。"""

    def __init__(self, display: Callable[[str], Dict]) -> None:
        """初始化独立队列；is_playing 可供语音会话过滤读取。"""
        self._display = display
        self.current_song = ""
        self.queue: List[str] = []
        self.is_playing = False

    def play_music(self, song_name: str) -> Dict:
        """模拟切换当前歌曲，保留等待队列。"""
        self.current_song = song_name
        self.is_playing = True
        self._display("兴奋")
        return self.music_status()

    def stop_music(self) -> Dict:
        """停止播放但保留当前歌曲与队列，遵循旧音乐状态契约。"""
        self.is_playing = False
        self._display("正常")
        return self.music_status()

    def next_song(self) -> Dict:
        """优先按序消费队列，空队列使用源推荐表的首首歌曲。"""
        song = (
            self.queue.pop(0) if self.queue else self._recommendations(None)[0]
        )
        return self.play_music(song)

    def add_to_queue(self, song_name: str) -> Dict:
        """保留重复歌曲和入队顺序，不自动开始播放。"""
        self.queue.append(song_name)
        return self.music_status()

    def recommend_songs(self, song_name: Optional[str] = None) -> Dict:
        """返回源静态推荐，不拉取在线歌曲或修改播放状态。"""
        songs = self._recommendations(song_name)
        return simulated("推荐歌曲 " + "、".join(songs), songs=songs)

    def _recommendations(self, song_name: Optional[str]) -> List[str]:
        """未指定歌曲时使用当前曲目，排除作为推荐依据的歌曲。"""
        seed = self.current_song if song_name is None else song_name
        songs = RECOMMENDATIONS.get(seed, ["小幸运", "青花瓷", "稻香", "夜曲"])
        return [song for song in songs if song != seed]

    def music_status(self) -> Dict:
        """返回播放快照，保持会话过滤所需的 is_playing 字段。"""
        return simulated(
            f"音乐 {'播放中' if self.is_playing else '已停止'}，"
            f"当前歌曲 {self.current_song}，队列 {self.queue}",
            is_playing=self.is_playing,
            current_song=self.current_song,
            queue=self.queue,
        )


def music_actions(music: MusicSimulation) -> Dict[str, ActionHandler]:
    """音乐能力集中声明播放、队列和查询的执行及参数契约。"""
    play = ActionHandler(music.play_music, validate_song)
    return {
        "play_music": play,
        "play_song": play,
        "add_to_queue": ActionHandler(music.add_to_queue, validate_song),
        "recommend_songs": ActionHandler(
            music.recommend_songs, validate_recommendation
        ),
        "stop_music": ActionHandler(music.stop_music),
        "next_song": ActionHandler(music.next_song),
        "music_status": ActionHandler(music.music_status),
    }


def validate_step(step: float = 5) -> None:
    """音量步长为非负有限百分比，结果按源0至100范围饱和。"""
    validate_number(step, "step")
    if step < 0:
        raise ValueError("step 不能为负数")


def validate_level(level: float = 50) -> None:
    """音量级别为有限数字；执行时保留源整数量化与饱和契约。"""
    validate_number(level, "level")


class VolumeSimulation:
    """独立管理音量和静音状态，不调用 amixer 或系统混音器。"""

    def __init__(self) -> None:
        """初始模拟音量为50，未静音。"""
        self.level = 50
        self.is_muted = False

    def volume_up(self, step: float = 5) -> Dict:
        """增加音量，保留静音开关。"""
        self.level = min(100, self.level + step)
        return self.volume_status()

    def volume_down(self, step: float = 5) -> Dict:
        """减少音量，保留静音开关。"""
        self.level = max(0, self.level - step)
        return self.volume_status()

    def volume_set(self, level: float = 50) -> Dict:
        """模拟源 level 的整数转换与0至100饱和。"""
        self.level = max(0, min(100, int(level)))
        return self.volume_status()

    def volume_mute(self) -> Dict:
        """静音但保留原音量。"""
        self.is_muted = True
        return self.volume_status()

    def volume_unmute(self) -> Dict:
        """取消静音，不重置音量。"""
        self.is_muted = False
        return self.volume_status()

    def volume_status(self) -> Dict:
        """返回模拟音量与静音快照。"""
        return simulated(
            f"音量 {self.level}，静音 {self.is_muted}",
            level=self.level,
            is_muted=self.is_muted,
        )


def volume_actions(volume: VolumeSimulation) -> Dict[str, ActionHandler]:
    """音量能力声明修改与查询动作，校验与实现保持相邻。"""
    return {
        "volume_up": ActionHandler(volume.volume_up, validate_step),
        "volume_down": ActionHandler(volume.volume_down, validate_step),
        "volume_set": ActionHandler(volume.volume_set, validate_level),
        "volume_mute": ActionHandler(volume.volume_mute),
        "volume_unmute": ActionHandler(volume.volume_unmute),
        "volume_status": ActionHandler(volume.volume_status),
    }


def wifi_status() -> Dict:
    """查询固定模拟网络，文档专用IP不代表主机真实连接。"""
    return simulated(
        "WiFi 已连接 simulated-network，IP 192.0.2.2",
        connected=True,
        ssid="simulated-network",
        ip="192.0.2.2",
    )


def show_wifi_info(display: Callable[[str], Dict]) -> Dict:
    """模拟LCD显示WiFi信息，不查询主机网络或创建屏幕驱动。"""
    display("wifi_info")
    return wifi_status()


def wifi_actions(display: Callable[[str], Dict]) -> Dict[str, ActionHandler]:
    """WiFi能力绑定LCD协作者，注册表无需了解显示参数。"""
    status = ActionHandler(wifi_status)
    return {
        "wifi_status": status,
        "get_wifi_ip": status,
        "show_wifi_info": ActionHandler(partial(show_wifi_info, display)),
    }


def simulate_cue(kind: str) -> Dict:
    """启动及错误提示音只输出日志，无播放器和音频产物。"""
    if kind not in ("startup", "error"):
        raise ValueError("未知提示音")
    return simulated("提示音 " + kind + "，不播放", cue=kind)
