"""
Spritesheet 2D 渲染器
通过 QLabel + QPixmap 直接渲染帧动画，不依赖 QWebEngineView
"""

import os
import random

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap

from .base_renderer import BaseRenderer


class SpriteRenderer(BaseRenderer):
    """Spritesheet 2D 渲染器"""

    # 状态 → 行号映射（兼容 InteractionDecider 输出）
    DEFAULT_STATE_MAP = {
        "idle": 0, "walk": 1, "run": 2, "jump": 3,
        "wave": 4, "fail": 5, "wait": 6, "review": 7, "work": 8,
        "nod_fast": 2, "nod_gentle": 1, "sleepy": 6,
        "sit_quietly": 0, "scared": 5, "think": 0,
        "happy": 1, "sad": 2, "surprised": 3,
        "angry": 5, "greet": 4, "wave_arm": 4, "bow": 4,
    }

    # 降级映射：当目标状态行不存在时的回退
    _FALLBACK_MAP = {
        "think": "idle",
        "greet": "wave",
        "wave_arm": "wave",
        "bow": "wave",
        "scared": "surprised",
        "sleepy": "idle",
        "sit_quietly": "idle",
        "angry": "fail",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widget = QWidget(parent)
        self._layout = QVBoxLayout(self._widget)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(self._widget)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background: transparent;")
        self._layout.addWidget(self._label)

        # Spritesheet 数据
        self._spritesheet = None    # QPixmap 原始图
        self._frame_w = 0
        self._frame_h = 0
        self._cols = 9
        self._rows = 8
        self._speed = 100           # ms per frame

        # 播放状态
        self._current_state = "idle"
        self._current_row = 0
        self._current_frame = 0
        self._state_map = dict(self.DEFAULT_STATE_MAP)

        # 帧缓存池 {(row, col): QPixmap}
        self._frame_cache = {}
        self._cache_max_size = 200

        # 定时器
        self._anim_timer = QTimer(self._widget)
        self._anim_timer.timeout.connect(self._next_frame)
        self._idle_timer = None

    def load(self, character_id, profile, characters_dir):
        """加载 Spritesheet"""
        appearance = profile.get("appearance", {})
        model_path = appearance.get("modelPath", "assets/spritesheet.png")
        if model_path.startswith("assets/"):
            model_path = model_path[len("assets/"):]

        sheet_path = os.path.join(characters_dir, character_id, model_path)
        config = appearance.get("spriteConfig", {})

        self._cols = config.get("columns", 9)
        self._rows = config.get("rows", 8)
        self._speed = config.get("defaultSpeed", 100)

        # 合并自定义状态映射
        custom_map = config.get("stateMap", {})
        self._state_map = dict(self.DEFAULT_STATE_MAP)
        self._state_map.update(custom_map)

        # 加载图片
        pixmap = QPixmap(sheet_path)
        if pixmap.isNull():
            print(f"[SpriteRenderer] Spritesheet not found: {sheet_path}")
            return False

        self._spritesheet = pixmap
        self._frame_w = config.get("frameWidth", pixmap.width() // self._cols)
        self._frame_h = config.get("frameHeight", pixmap.height() // self._rows)

        # 清空帧缓存
        self._frame_cache.clear()

        # 开始播放待机动画
        self._play_state("idle")
        self.model_ready.emit(character_id)
        return True

    def play_motion(self, name, group=""):
        self._play_state(name)

    def set_expression(self, name):
        self._play_state(name)

    def set_random_motion(self):
        self._play_state(random.choice(list(self._state_map.keys())))

    def mouse_follow(self, x, y):
        pass  # 2D Spritesheet 不支持眼神跟随

    def start_idle_timer(self, interval_ms=5000):
        self.stop_idle_timer()
        self._idle_timer = QTimer(self._widget)
        self._idle_timer.timeout.connect(self._idle_action)
        self._idle_timer.start(interval_ms)

    def stop_idle_timer(self):
        if self._idle_timer:
            self._idle_timer.stop()
            self._idle_timer = None

    def set_scale(self, factor):
        if not self._spritesheet:
            return
        frame = self._get_frame(self._current_row, self._current_frame)
        scaled = frame.scaled(
            int(frame.width() * factor),
            int(frame.height() * factor),
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self._label.setPixmap(scaled)

    def get_widget(self):
        return self._widget

    def get_cache_stats(self):
        return {
            "type": "sprite",
            "cached_frames": len(self._frame_cache),
            "max_size": self._cache_max_size,
            "spritesheet_size": f"{self._spritesheet.width()}x{self._spritesheet.height()}"
                if self._spritesheet else "N/A"
        }

    def cleanup(self):
        self._anim_timer.stop()
        self.stop_idle_timer()
        self._frame_cache.clear()
        self._spritesheet = None
        self._label.clear()

    # ========== 内部方法 ==========

    def _resolve_state(self, name: str) -> int:
        """解析状态名到行号，支持降级回退"""
        row = self._state_map.get(name)
        if row is not None and row < self._rows:
            return row
        # 降级
        fallback_name = self._FALLBACK_MAP.get(name, "idle")
        row = self._state_map.get(fallback_name, 0)
        return row if row < self._rows else 0

    def _get_frame(self, row, col):
        """获取帧（带 LRU 缓存）"""
        key = (row, col)
        if key not in self._frame_cache:
            if not self._spritesheet:
                return QPixmap()
            x = col * self._frame_w
            y = row * self._frame_h
            self._frame_cache[key] = self._spritesheet.copy(
                x, y, self._frame_w, self._frame_h
            )
            # 缓存淘汰
            if len(self._frame_cache) > self._cache_max_size:
                oldest = next(iter(self._frame_cache))
                del self._frame_cache[oldest]
        return self._frame_cache[key]

    def _play_state(self, state):
        """播放指定状态的动画"""
        if not self._spritesheet:
            return

        row = self._resolve_state(state)

        state_changed = (state != self._current_state)
        self._current_state = state
        self._current_row = row

        if state_changed:
            self._current_frame = 0

        self._anim_timer.start(self._speed)
        self._render_current_frame()

    def _next_frame(self):
        """播放下一帧"""
        if not self._spritesheet:
            return
        self._current_frame = (self._current_frame + 1) % self._cols
        self._render_current_frame()
        # 一轮动画结束
        if self._current_frame == 0:
            self.motion_played.emit(self._current_state)

    def _render_current_frame(self):
        """渲染当前帧到 QLabel"""
        if not self._spritesheet:
            return
        frame = self._get_frame(self._current_row, self._current_frame)
        if not frame.isNull():
            self._label.setPixmap(frame)

    def _idle_action(self):
        """空闲时随机切换动作"""
        self._play_state(random.choice(["idle", "wait", "review"]))
