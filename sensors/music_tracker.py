"""
音乐播放记录管理模块
负责记录、存储、查询音乐播放历史
"""

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


class MusicTracker:
    """音乐播放记录管理器"""

    def __init__(self, db_path: str = "characters/default/music_history.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._last_track: Optional[Dict] = None
        self._last_track_time: float = 0
        self._dedup_window: float = 30.0  # 30 秒内同一首歌不重复记录

        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        # 初始化数据库
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS play_history (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        title       TEXT NOT NULL,
                        artist      TEXT DEFAULT '',
                        album       TEXT DEFAULT '',
                        platform    TEXT DEFAULT '',
                        play_time   DATETIME NOT NULL,
                        duration    INTEGER DEFAULT 0,
                        source      TEXT DEFAULT 'smtc'
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_play_time
                    ON play_history(play_time)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_artist
                    ON play_history(artist)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_title
                    ON play_history(title)
                """)
                conn.commit()
            finally:
                conn.close()

    def record_play(
        self,
        title: str,
        artist: str = "",
        album: str = "",
        platform: str = "",
        source: str = "smtc"
    ) -> bool:
        """
        记录一次播放
        返回是否实际写入（去重后）
        """
        if not title:
            return False

        # 去重检查
        current_time = time.time()
        track_key = f"{title}|{artist}"

        if self._last_track and self._last_track.get("key") == track_key:
            if current_time - self._last_track_time < self._dedup_window:
                return False

        # 记录到数据库
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.execute(
                    """
                    INSERT INTO play_history (title, artist, album, platform, play_time, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (title, artist, album, platform, datetime.now().isoformat(), source)
                )
                conn.commit()
                conn.close()

                # 更新去重状态
                self._last_track = {"key": track_key, "title": title, "artist": artist}
                self._last_track_time = current_time
                return True
            except Exception as e:
                print(f"记录播放失败: {e}")
                return False

    def get_recent_plays(self, hours: int = 24) -> List[Dict]:
        """获取最近 N 小时的播放记录"""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT title, artist, album, platform, play_time, duration, source
                    FROM play_history
                    WHERE play_time >= ?
                    ORDER BY play_time DESC
                    """,
                    (cutoff,)
                )
                results = [dict(row) for row in cursor.fetchall()]
                conn.close()
                return results
            except Exception as e:
                print(f"查询播放记录失败: {e}")
                return []

    def get_top_songs(self, days: int = 7, limit: int = 20) -> List[Dict]:
        """获取最近 N 天常听歌曲 Top"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    """
                    SELECT title, artist, COUNT(*) as plays
                    FROM play_history
                    WHERE play_time >= ?
                    GROUP BY title, artist
                    ORDER BY plays DESC
                    LIMIT ?
                    """,
                    (cutoff, limit)
                )
                results = [
                    {"title": row[0], "artist": row[1], "plays": row[2]}
                    for row in cursor.fetchall()
                ]
                conn.close()
                return results
            except Exception as e:
                print(f"查询常听歌曲失败: {e}")
                return []

    def get_top_artists(self, days: int = 30, limit: int = 10) -> List[Dict]:
        """获取最近 N 天常听艺术家 Top"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    """
                    SELECT artist, COUNT(*) as plays
                    FROM play_history
                    WHERE play_time >= ? AND artist != ''
                    GROUP BY artist
                    ORDER BY plays DESC
                    LIMIT ?
                    """,
                    (cutoff, limit)
                )
                results = [
                    {"artist": row[0], "plays": row[1]}
                    for row in cursor.fetchall()
                ]
                conn.close()
                return results
            except Exception as e:
                print(f"查询常听艺术家失败: {e}")
                return []

    def get_listening_pattern(self, days: int = 30) -> Dict[str, float]:
        """获取播放时段偏好（百分比）"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    """
                    SELECT play_time FROM play_history
                    WHERE play_time >= ?
                    """,
                    (cutoff,)
                )

                pattern = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
                total = 0

                for row in cursor.fetchall():
                    try:
                        dt = datetime.fromisoformat(row[0])
                        hour = dt.hour
                        if 6 <= hour < 12:
                            pattern["morning"] += 1
                        elif 12 <= hour < 18:
                            pattern["afternoon"] += 1
                        elif 18 <= hour < 24:
                            pattern["evening"] += 1
                        else:
                            pattern["night"] += 1
                        total += 1
                    except Exception:
                        pass

                conn.close()

                # 转换为百分比
                if total > 0:
                    for key in pattern:
                        pattern[key] = round(pattern[key] / total * 100, 1)

                return pattern
            except Exception as e:
                print(f"查询播放时段失败: {e}")
                return {"morning": 25, "afternoon": 25, "evening": 25, "night": 25}

    def get_favorite_platform(self, days: int = 30) -> str:
        """获取最常用的播放平台"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    """
                    SELECT platform, COUNT(*) as cnt
                    FROM play_history
                    WHERE play_time >= ? AND platform != ''
                    GROUP BY platform
                    ORDER BY cnt DESC
                    LIMIT 1
                    """,
                    (cutoff,)
                )
                row = cursor.fetchone()
                conn.close()
                return row[0] if row else ""
            except Exception:
                return ""

    def get_stats(self, days: int = 30) -> Dict:
        """获取播放统计数据"""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total_plays,
                        COUNT(DISTINCT title || '|' || artist) as unique_songs,
                        COUNT(DISTINCT artist) as unique_artists,
                        SUM(duration) as total_duration
                    FROM play_history
                    WHERE play_time >= ?
                    """,
                    (cutoff,)
                )
                row = cursor.fetchone()
                conn.close()

                return {
                    "total_plays": row[0] or 0,
                    "unique_songs": row[1] or 0,
                    "unique_artists": row[2] or 0,
                    "total_hours": round((row[3] or 0) / 3600, 1),
                }
            except Exception as e:
                print(f"查询统计数据失败: {e}")
                return {
                    "total_plays": 0,
                    "unique_songs": 0,
                    "unique_artists": 0,
                    "total_hours": 0,
                }

    def get_database_size(self) -> int:
        """获取数据库文件大小（字节）"""
        try:
            return os.path.getsize(self.db_path)
        except Exception:
            return 0

    def cleanup_old_records(self, keep_days: int = 90):
        """清理超过 N 天的旧记录"""
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
        with self._lock:
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.execute(
                    "DELETE FROM play_history WHERE play_time < ?",
                    (cutoff,)
                )
                deleted = cursor.rowcount
                conn.commit()
                conn.close()

                if deleted > 0:
                    print(f"已清理 {deleted} 条过期播放记录")

                return deleted
            except Exception as e:
                print(f"清理旧记录失败: {e}")
                return 0
