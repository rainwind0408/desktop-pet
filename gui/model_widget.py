"""
模型渲染路由层
根据 profile.appearance.styleType 自动选择对应的 Renderer：
  - "live2d" / "vrm" → WebEngineRenderer (QWebEngineView + JS 引擎)
  - "sprite"         → SpriteRenderer   (QLabel + QPixmap)
"""

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QMouseEvent

from .renderers import WebEngineRenderer, SpriteRenderer


CHARACTERS_DIR = __import__('os').path.abspath(
    __import__('os').path.join(__import__('os').path.dirname(__file__), "..", "characters")
)


class MouseTransparentOverlay(QWidget):
    """透明覆盖层，用于捕获鼠标事件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):
        pass

    def mousePressEvent(self, event):
        if self.parent():
            new_pos = self.mapToParent(event.pos())
            new_event = QMouseEvent(
                event.type(), new_pos, event.globalPos(),
                event.button(), event.buttons(), event.modifiers()
            )
            self.parent().mousePressEvent(new_event)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.parent():
            new_pos = self.mapToParent(event.pos())
            new_event = QMouseEvent(
                event.type(), new_pos, event.globalPos(),
                event.button(), event.buttons(), event.modifiers()
            )
            self.parent().mouseMoveEvent(new_event)
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.parent():
            new_pos = self.mapToParent(event.pos())
            new_event = QMouseEvent(
                event.type(), new_pos, event.globalPos(),
                event.button(), event.buttons(), event.modifiers()
            )
            self.parent().mouseReleaseEvent(new_event)
        event.accept()

    def contextMenuEvent(self, event):
        if self.parent():
            parent = self.parent()
            while parent:
                if hasattr(parent, 'show_context_menu'):
                    parent.show_context_menu(event.globalPos())
                    event.accept()
                    return
                parent = parent.parent()
        event.accept()


# styleType → Renderer 类映射
RENDERER_MAP = {
    "live2d": WebEngineRenderer,
    "vrm": WebEngineRenderer,
    "sprite": SpriteRenderer,
}


class ModelWidget(QWidget):
    """模型渲染路由层 — 根据 styleType 自动选择 Renderer"""

    model_ready = pyqtSignal(str)
    motion_played = pyqtSignal(str)
    fallback_visible = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = None
        self._renderer_type = None
        self._character_id = None
        self._profile = None

        # 拖拽状态
        self._drag_start_pos = None
        self._is_dragging = False

        self._init_ui()

    def _init_ui(self):
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._fallback_label = QLabel(self)
        self._fallback_label.setAlignment(Qt.AlignCenter)
        self._fallback_label.setStyleSheet("""
            QLabel {
                background-color: rgba(255, 255, 255, 0.3);
                border-radius: 20px;
                border: 2px dashed rgba(150, 150, 150, 0.5);
                color: #666;
                font-size: 16px;
            }
        """)
        self._fallback_label.hide()
        self._layout.addWidget(self._fallback_label)

        self._overlay = MouseTransparentOverlay(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_overlay'):
            self._overlay.setGeometry(self.rect())

    # ========== 拖拽逻辑（保留在路由层）==========

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPos()
            self._is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_start_pos:
            delta = event.globalPos() - self._drag_start_pos
            if not self._is_dragging and (abs(delta.x()) > 3 or abs(delta.y()) > 3):
                self._is_dragging = True
            if self._is_dragging:
                window = self.window()
                if window:
                    window.move(window.pos() + delta)
                self._drag_start_pos = event.globalPos()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = None
            self._is_dragging = False
            event.accept()

    def contextMenuEvent(self, event):
        parent = self.parent()
        while parent:
            if hasattr(parent, 'show_context_menu'):
                parent.show_context_menu(event.globalPos())
                event.accept()
                return
            parent = parent.parent()
        super().contextMenuEvent(event)

    # ========== 核心路由逻辑 ==========

    def load_character(self, character_id, profile=None):
        """加载角色 — 根据 styleType 自动选择 Renderer"""
        self._character_id = character_id
        self._profile = profile

        appearance = profile.get("appearance", {}) if profile else {}
        style_type = appearance.get("styleType", "live2d")

        # 获取对应的 Renderer 类
        renderer_class = RENDERER_MAP.get(style_type)
        if not renderer_class:
            print(f"[ModelWidget] Unknown styleType: {style_type}")
            self._show_fallback(f"未知渲染类型: {style_type}")
            return

        # 同类型切换或 WebEngineRenderer 间切换（vrm ↔ live2d）：复用 Renderer
        if self._renderer and (self._renderer_type == style_type or
                               isinstance(self._renderer, WebEngineRenderer)):
            self._renderer.load(character_id, profile, CHARACTERS_DIR)
            return

        # 跨类型切换：销毁旧 Renderer，创建新的
        self._cleanup_renderer()

        self._renderer = renderer_class(self)
        self._renderer_type = style_type

        # 连接信号
        self._renderer.model_ready.connect(self.model_ready.emit)
        self._renderer.motion_played.connect(self.motion_played.emit)
        self._renderer.fallback_visible.connect(self.fallback_visible.emit)

        # 插入 Renderer 的 widget（在 fallback_label 之前）
        widget = self._renderer.get_widget()
        self._layout.insertWidget(0, widget)

        # 加载角色
        success = self._renderer.load(character_id, profile, CHARACTERS_DIR)
        if not success:
            name = profile.get("name", character_id)
            self._show_fallback(f"角色 {name} 加载失败")

        self._fallback_label.hide()

    def _cleanup_renderer(self):
        """清理当前 Renderer"""
        if self._renderer:
            widget = self._renderer.get_widget()
            self._layout.removeWidget(widget)
            self._renderer.cleanup()
            widget.deleteLater()
            self._renderer = None
            self._renderer_type = None

    def _show_fallback(self, text):
        """显示降级界面"""
        self._fallback_label.setText(text)
        self._fallback_label.show()
        self.fallback_visible.emit(True)

    # ========== 公共接口 — 委托给 Renderer ==========

    def play_motion(self, motion_name, group=""):
        if self._renderer:
            self._renderer.play_motion(motion_name, group)

    def set_expression(self, expression_name):
        if self._renderer:
            self._renderer.set_expression(expression_name)

    def set_random_motion(self):
        if self._renderer:
            self._renderer.set_random_motion()

    def mouse_follow(self, x, y):
        if self._renderer:
            self._renderer.mouse_follow(x, y)

    def start_idle_timer(self, interval_ms=5000):
        if self._renderer:
            self._renderer.start_idle_timer(interval_ms)

    def stop_idle_timer(self):
        if self._renderer:
            self._renderer.stop_idle_timer()

    def set_scale(self, factor):
        if self._renderer:
            self._renderer.set_scale(factor)

    def get_render_mode(self):
        return self._renderer_type

    def get_cache_stats(self):
        if self._renderer and hasattr(self._renderer, 'get_cache_stats'):
            return self._renderer.get_cache_stats()
        return None

    def get_manager_state(self):
        if self._renderer and hasattr(self._renderer, '_model_manager'):
            mm = self._renderer._model_manager
            if mm:
                return mm.get_state()
        return None

    def cleanup(self):
        self._cleanup_renderer()


# 向后兼容
Live2DWidget = ModelWidget
