"""
多模态感知模块
负责音乐感知（Windows SMTC）、窗口标题检测、视频感知
"""

import ctypes
import ctypes.wintypes
import json
import os
import re
import threading
import time
from typing import Callable, Dict, List, Optional


# Windows SMTC 相关常量和结构
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 窗口标题检测的视频播放器关键词
VIDEO_PLAYER_KEYWORDS = [
    "哔哩哔哩", "bilibili", "抖音", "TikTok", "YouTube",
    "腾讯视频", "爱奇艺", "优酷", "芒果TV",
    "PotPlayer", "VLC", "mpc", "MPC-HC", "MPC-BE",
    "暴风影音", "播放器", "Player",
]

# 音乐播放器进程名
MUSIC_PLAYER_PROCESSES = {
    "cloudmusic": "网易云音乐",
    "qqmusic": "QQ音乐",
    "spotify": "Spotify",
    "kugou": "酷狗音乐",
    "kuwo": "酷我音乐",
    "foobar2000": "foobar2000",
    "MusicPlayer": "音乐播放器",
    "kgmusic": "酷狗音乐",
    "kwmusic": "酷我音乐",
    "AppleMusic": "Apple Music",
    "iTunes": "iTunes",
    "汽水音乐": "汽水音乐",
    "qishui": "汽水音乐",
}


def get_foreground_window_title() -> str:
    """获取当前前台窗口标题"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def get_foreground_window_process_name() -> str:
    """获取前台窗口的进程名"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        process_handle = kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value
        )
        if not process_handle:
            return ""

        try:
            buf = ctypes.create_unicode_buffer(512)
            psapi = ctypes.windll.psapi
            psapi.GetModuleBaseNameW(process_handle, None, buf, 512)
            return buf.value
        finally:
            kernel32.CloseHandle(process_handle)
    except Exception:
        return ""


class MediaSensor:
    """多模态感知器：检测音乐播放、视频播放、窗口活动"""

    def __init__(self, poll_interval: float = 3.0):
        self.poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable] = None

        # 当前感知状态
        self.state: Dict = {
            "music_playing": False,
            "music_title": "",
            "music_artist": "",
            "music_album": "",
            "music_platform": "",
            "music_bpm": 0,
            "music_genre": "",
            "video_playing": False,
            "video_title": "",
            "video_tags": [],
            "active_window_title": "",
            "active_app": "",
        }

        # SMTC 支持检测
        self._smtc_available = False
        self._init_smtc()

    def _init_smtc(self):
        """初始化 Windows SMTC 接口"""
        try:
            import winsdk.windows.media as wmedia
            import winsdk.windows.media.control as wmedia_ctrl
            self._smtc_available = True
            self._wmedia = wmedia
            self._wmedia_ctrl = wmedia_ctrl
        except ImportError:
            self._smtc_available = False

    def start(self, callback: Optional[Callable] = None):
        """启动后台感知线程"""
        if self._running:
            return
        self._running = True
        self._callback = callback
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止感知"""
        self._running = False

    def get_state(self) -> Dict:
        """获取当前感知状态"""
        return dict(self.state)

    def _poll_loop(self):
        """主轮询循环"""
        while self._running:
            try:
                self._update_state()
            except Exception as e:
                print(f"媒体感知轮询错误: {e}")
            time.sleep(self.poll_interval)

    def _update_state(self):
        """更新感知状态"""
        old_state = dict(self.state)

        # 更新窗口信息
        self._update_window_info()

        # 更新音乐信息
        self._update_music_info()

        # 检测视频播放
        self._detect_video()

        # 状态变化时通知
        if self._callback and self._state_changed(old_state):
            self._callback(dict(self.state))

    def _update_window_info(self):
        """更新前台窗口信息"""
        title = get_foreground_window_title()
        process = get_foreground_window_process_name()
        self.state["active_window_title"] = title
        self.state["active_app"] = process

    def _update_music_info(self):
        """更新音乐播放信息"""
        if self._smtc_available:
            self._update_music_smtc()
        else:
            self._update_music_from_title()

    def _update_music_smtc(self):
        """通过 Windows SMTC 获取音乐信息"""
        try:
            import asyncio
            import winsdk.windows.media.control as wmedia_ctrl

            async def get_media_info():
                manager = await wmedia_ctrl.GlobalSystemMediaTransportControlsSessionManager.request_async()
                session = manager.get_current_session()
                if not session:
                    return None
                info = await session.try_get_media_properties_async()
                playback = session.get_playback_info()
                # 获取来源应用
                source_app = session.source_app_user_model_id or ""
                return {
                    "title": info.title or "",
                    "artist": info.artist or "",
                    "album": info.album_title or "",
                    "playing": playback.playback_status == 4,  # Playing
                    "source_app": source_app,
                }

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(get_media_info())
                if result:
                    self.state["music_playing"] = result["playing"]
                    self.state["music_title"] = result["title"]
                    self.state["music_artist"] = result["artist"]
                    self.state["music_album"] = result.get("album", "")
                    # 识别平台
                    source_app = result.get("source_app", "")
                    self.state["music_platform"] = self._identify_platform(source_app)
                    if not result["playing"]:
                        self.state["music_playing"] = False
            finally:
                loop.close()
        except Exception:
            self._update_music_from_title()

    def _update_music_from_title(self):
        """从窗口标题推断音乐播放（fallback）"""
        title = self.state.get("active_window_title", "")
        process = self.state.get("active_app", "")

        # 检查是否是音乐播放器
        is_music_app = False
        app_name = ""
        platform = ""
        for proc_key, name in MUSIC_PLAYER_PROCESSES.items():
            if proc_key.lower() in process.lower() or proc_key.lower() in title.lower():
                is_music_app = True
                app_name = name
                platform = name
                break

        if is_music_app:
            self.state["music_playing"] = True
            self.state["music_platform"] = platform
            # 尝试从标题提取歌名
            # 常见格式: "歌名 - 歌手" 或 "歌名 - 歌手 - 网易云音乐"
            match = re.search(r'^(.+?)\s*[-–—]\s*(.+?)(?:\s*[-–—]|$)', title)
            if match:
                self.state["music_title"] = match.group(1).strip()
                self.state["music_artist"] = match.group(2).strip()
            else:
                self.state["music_title"] = title.replace(app_name, "").strip(" -–—")
                self.state["music_artist"] = ""
        else:
            self.state["music_playing"] = False
            self.state["music_title"] = ""
            self.state["music_artist"] = ""
            self.state["music_platform"] = ""

    def _identify_platform(self, source_app: str) -> str:
        """根据 SMTC 来源应用识别音乐平台"""
        source_lower = source_app.lower()

        platform_map = {
            "cloudmusic": "网易云音乐",
            "netease": "网易云音乐",
            "qqmusic": "QQ音乐",
            "spotify": "Spotify",
            "kugou": "酷狗音乐",
            "kuwo": "酷我音乐",
            "foobar2000": "foobar2000",
            "apple music": "Apple Music",
            "itunes": "iTunes",
            "汽水音乐": "汽水音乐",
            "qishui": "汽水音乐",
        }

        for key, name in platform_map.items():
            if key in source_lower:
                return name

        # 如果无法识别，尝试从窗口标题获取
        title = self.state.get("active_window_title", "")
        for proc_key, name in MUSIC_PLAYER_PROCESSES.items():
            if proc_key.lower() in title.lower():
                return name

        return ""

    def _detect_video(self):
        """检测视频播放"""
        title = self.state.get("active_window_title", "")
        process = self.state.get("active_app", "")

        # 检查是否是视频播放器
        is_video = False
        for keyword in VIDEO_PLAYER_KEYWORDS:
            if keyword.lower() in title.lower() or keyword.lower() in process.lower():
                is_video = True
                break

        if is_video:
            self.state["video_playing"] = True
            # 清理标题中的平台名
            clean_title = title
            for keyword in VIDEO_PLAYER_KEYWORDS:
                clean_title = re.sub(re.escape(keyword), "", clean_title, flags=re.IGNORECASE)
            clean_title = clean_title.strip(" -–—·|_")
            self.state["video_title"] = clean_title if clean_title else title
        else:
            self.state["video_playing"] = False
            self.state["video_title"] = ""
            self.state["video_tags"] = []

    def _state_changed(self, old: Dict) -> bool:
        """检测状态是否发生有意义的变化"""
        keys_to_check = [
            "music_playing", "music_title", "music_artist", "music_platform",
            "video_playing", "video_title", "active_app"
        ]
        return any(old.get(k) != self.state.get(k) for k in keys_to_check)

    def get_perception_summary(self) -> str:
        """生成人类可读的感知摘要"""
        parts = []
        if self.state["music_playing"]:
            title = self.state["music_title"] or "未知歌曲"
            artist = self.state["music_artist"]
            if artist:
                parts.append(f"正在听 {artist} 的《{title}》")
            else:
                parts.append(f"正在听《{title}》")

        if self.state["video_playing"]:
            title = self.state["video_title"] or "未知视频"
            parts.append(f"正在看视频: {title}")

        if not parts:
            app = self.state.get("active_app", "")
            if app:
                parts.append(f"正在使用 {app}")
            else:
                parts.append("空闲中")

        return "，".join(parts)
