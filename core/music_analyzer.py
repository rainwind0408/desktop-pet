"""
音乐数据分析模块
负责分析播放历史、生成音乐画像
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from sensors.music_tracker import MusicTracker


class MusicAnalyzer:
    """音乐数据分析器"""

    def __init__(self, tracker: MusicTracker, profile_path: str = "characters/default/music_profile.json"):
        self.tracker = tracker
        self.profile_path = profile_path
        self._profile: Optional[Dict] = None

    def generate_profile(self) -> Dict:
        """生成完整的音乐画像"""
        stats_7d = self.tracker.get_stats(days=7)
        stats_30d = self.tracker.get_stats(days=30)

        profile = {
            "updated_at": datetime.now().isoformat(),
            "stats": {
                "total_plays": stats_30d["total_plays"],
                "total_hours": stats_30d["total_hours"],
                "unique_songs": stats_30d["unique_songs"],
                "unique_artists": stats_30d["unique_artists"],
            },
            "top_songs_7d": self.tracker.get_top_songs(days=7, limit=20),
            "top_songs_30d": self.tracker.get_top_songs(days=30, limit=50),
            "top_artists_30d": self.tracker.get_top_artists(days=30, limit=10),
            "listening_pattern": self.tracker.get_listening_pattern(days=30),
            "favorite_platform": self.tracker.get_favorite_platform(days=30),
            "weekly_trend": self._calculate_weekly_trend(),
        }

        # 保存到文件
        self._save_profile(profile)
        self._profile = profile

        return profile

    def get_profile(self) -> Dict:
        """获取音乐画像（优先从缓存读取）"""
        if self._profile:
            return self._profile

        # 尝试从文件加载
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, 'r', encoding='utf-8') as f:
                    self._profile = json.load(f)
                    return self._profile
            except Exception:
                pass

        # 生成新画像
        return self.generate_profile()

    def get_listening_summary(self) -> str:
        """生成人类可听的音乐摘要"""
        profile = self.get_profile()
        stats = profile.get("stats", {})

        parts = []

        # 基本统计
        total_plays = stats.get("total_plays", 0)
        if total_plays > 0:
            parts.append(f"最近 30 天共播放了 {total_plays} 首歌曲")

        # 常听歌曲
        top_songs = profile.get("top_songs_7d", [])
        if top_songs:
            top3 = top_songs[:3]
            songs_str = "、".join([f"《{s['title']}》" for s in top3])
            parts.append(f"最近常听{songs_str}")

        # 常听艺术家
        top_artists = profile.get("top_artists_30d", [])
        if top_artists:
            top3 = top_artists[:3]
            artists_str = "、".join([a["artist"] for a in top3])
            parts.append(f"最喜欢的歌手是{artists_str}")

        # 播放时段
        pattern = profile.get("listening_pattern", {})
        if pattern:
            max_period = max(pattern.items(), key=lambda x: x[1])
            period_names = {
                "morning": "早上",
                "afternoon": "下午",
                "evening": "晚上",
                "night": "深夜"
            }
            period_name = period_names.get(max_period[0], "")
            if period_name and max_period[1] > 30:
                parts.append(f"最喜欢在{period_name}听歌")

        if not parts:
            return "还没有足够的音乐播放数据"

        return "。".join(parts) + "。"

    def get_mood_hint(self) -> str:
        """基于音乐偏好生成情绪提示（供角色对话使用）"""
        profile = self.get_profile()
        top_songs = profile.get("top_songs_7d", [])

        if not top_songs:
            return ""

        # 分析歌曲名称中的情绪关键词
        sad_keywords = ["伤", "泪", "哭", "痛", "离", "别", "忘", "空", "独", "寂寞", "孤单"]
        happy_keywords = ["快乐", "开心", "笑", "阳光", "幸福", "甜", "爱", "喜欢"]
        calm_keywords = ["安静", "夜", "星", "月", "风", "雨", "海", "梦"]

        # 统计情绪倾向
        mood_scores = {"sad": 0, "happy": 0, "calm": 0, "neutral": 0}

        for song in top_songs[:10]:
            title = song.get("title", "")
            artist = song.get("artist", "")
            text = title + artist

            for kw in sad_keywords:
                if kw in text:
                    mood_scores["sad"] += 1
                    break
            for kw in happy_keywords:
                if kw in text:
                    mood_scores["happy"] += 1
                    break
            for kw in calm_keywords:
                if kw in text:
                    mood_scores["calm"] += 1
                    break
            else:
                mood_scores["neutral"] += 1

        # 生成情绪提示
        max_mood = max(mood_scores.items(), key=lambda x: x[1])

        mood_hints = {
            "sad": "主人最近听的歌有些伤感，可以多关心一下",
            "happy": "主人最近听的歌很欢快，心情应该不错",
            "calm": "主人最近喜欢安静的音乐，可能在享受独处时光",
            "neutral": "",
        }

        return mood_hints.get(max_mood[0], "")

    def _calculate_weekly_trend(self) -> Dict:
        """计算每周播放趋势"""
        stats_7d = self.tracker.get_stats(days=7)
        stats_14d = self.tracker.get_stats(days=14)

        plays_this_week = stats_7d["total_plays"]
        plays_last_week = stats_14d["total_plays"] - plays_this_week

        if plays_last_week > 0:
            change_ratio = (plays_this_week - plays_last_week) / plays_last_week
            if change_ratio > 0.2:
                trend = "increasing"
            elif change_ratio < -0.2:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "new"

        return {
            "plays_this_week": plays_this_week,
            "plays_last_week": plays_last_week,
            "trend": trend,
        }

    def _save_profile(self, profile: Dict):
        """保存画像到文件"""
        try:
            os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
            with open(self.profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存音乐画像失败: {e}")

    def build_music_prompt(self) -> str:
        """构建音乐相关的系统提示词片段"""
        profile = self.get_profile()
        stats = profile.get("stats", {})

        if stats.get("total_plays", 0) == 0:
            return ""

        parts = []

        # 常听歌曲
        top_songs = profile.get("top_songs_7d", [])
        if top_songs:
            top5 = top_songs[:5]
            songs_list = []
            for s in top5:
                if s.get("artist"):
                    songs_list.append(f"{s['artist']}的《{s['title']}》")
                else:
                    songs_list.append(f"《{s['title']}》")
            parts.append(f"主人最近常听：{'、'.join(songs_list)}")

        # 常听艺术家
        top_artists = profile.get("top_artists_30d", [])
        if top_artists:
            top3 = top_artists[:3]
            artists_list = [a["artist"] for a in top3]
            parts.append(f"喜欢的歌手：{'、'.join(artists_list)}")

        # 播放时段
        pattern = profile.get("listening_pattern", {})
        if pattern:
            max_period = max(pattern.items(), key=lambda x: x[1])
            period_names = {
                "morning": "早上",
                "afternoon": "下午",
                "evening": "晚上",
                "night": "深夜"
            }
            period_name = period_names.get(max_period[0], "")
            if period_name and max_period[1] > 30:
                parts.append(f"常在{period_name}听歌")

        # 情绪提示
        mood_hint = self.get_mood_hint()
        if mood_hint:
            parts.append(mood_hint)

        if not parts:
            return ""

        return "[音乐偏好]\n" + "\n".join(parts)
