"""
3D 模型渲染组件
支持 Live2D 和 VRM 两种模型格式
通过 QWebEngineView 嵌入渲染网页
"""

import os

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWebEngineWidgets import QWebEngineView

from .live2d_bridge import Live2DBridge


CHARACTERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "characters")
)


class ModelWidget(QWidget):
    """3D 模型渲染组件（支持 Live2D 和 VRM）"""

    model_ready = pyqtSignal(str)
    motion_played = pyqtSignal(str)
    fallback_visible = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._character_id = None
        self._profile = None
        self._bridge = Live2DBridge(self)
        self._use_fallback = False
        self._model_type = "live2d"  # 'live2d' | 'vrm'
        self._init_ui()
        self._connect_bridge()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

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

        self._web_view = QWebEngineView(self)
        self._web_view.setAttribute(Qt.WA_TranslucentBackground)
        self._web_view.page().setBackgroundColor(Qt.transparent)
        self._web_view.setStyleSheet("background: transparent;")

        layout.addWidget(self._web_view)
        layout.addWidget(self._fallback_label)

    def _connect_bridge(self):
        self._bridge.model_loaded.connect(self._on_model_loaded)
        self._bridge.model_error.connect(self._on_model_error)
        self._bridge.motion_started.connect(self._on_motion_started)
        self._bridge.motion_finished.connect(self._on_motion_finished)

    def load_character(self, character_id, profile=None):
        self._character_id = character_id
        self._profile = profile

        # 获取模型类型
        appearance = profile.get("appearance", {}) if profile else {}
        self._model_type = appearance.get("styleType", "live2d")

        template_path = self._find_template(character_id)
        if template_path and os.path.exists(template_path):
            self._bridge.create_channel(self._web_view)
            # 断开旧的连接，避免重复
            try:
                self._web_view.loadFinished.disconnect()
            except TypeError:
                pass
            # 连接 loadFinished 信号，注入角色配置
            self._web_view.loadFinished.connect(self._on_page_loaded)
            url = QUrl.fromLocalFile(os.path.abspath(template_path))
            self._web_view.load(url)
            self._web_view.show()
            self._fallback_label.hide()
            self._use_fallback = False
        else:
            name = profile.get("name", character_id) if profile else character_id
            self._show_fallback(f"角色\n{name}\n等待模型文件...")
            self.fallback_visible.emit(True)

    def _on_page_loaded(self, ok):
        """页面加载完成后注入角色配置"""
        if not ok or not self._profile:
            return

        appearance = self._profile.get("appearance", {})
        name = self._profile.get("name", self._character_id)
        model_path = appearance.get("modelPath", "model/model.model3.json")
        style_type = appearance.get("styleType", "live2d")
        avatar = self._profile.get("preferences", {}).get("avatar", "🎀")

        # 将 modelPath 转换为相对于 index.html 的路径
        # index.html 在 characters/{id}/assets/，模型在 characters/{id}/assets/model/
        # 所以 modelPath 应该是 "model/character.vrm" 这样的相对路径
        if model_path.startswith("assets/"):
            model_path = model_path[len("assets/"):]

        # 构建 JSON 配置
        import json
        config_json = json.dumps({
            "name": name,
            "avatar": avatar,
            "modelPath": model_path,
            "styleType": style_type,
            "scale": 1.0
        }, ensure_ascii=False)

        # 注入配置并调用 updateConfig
        js = f"""
        try {{
            window._configInjected = true;
            updateConfig({config_json});
        }} catch(e) {{
            console.error('Config injection error:', e);
        }}
        """
        self._web_view.page().runJavaScript(js)

    def _find_template(self, character_id):
        candidates = [
            os.path.join(CHARACTERS_DIR, character_id, "assets", "index.html"),
            os.path.join(CHARACTERS_DIR, character_id, "assets", "model", "index.html"),
            os.path.join(CHARACTERS_DIR, character_id, "index.html"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def _show_fallback(self, text):
        self._fallback_label.setText(text)
        self._fallback_label.show()
        self._web_view.hide()
        self._use_fallback = True
        self.fallback_visible.emit(True)

    def play_motion(self, motion_name, group=""):
        if self._use_fallback:
            return
        js = f"playMotion('{motion_name}', '{group}')"
        self._web_view.page().runJavaScript(js)

    def set_expression(self, expression_name):
        if self._use_fallback:
            return
        js = f"setExpression('{expression_name}')"
        self._web_view.page().runJavaScript(js)

    def set_random_motion(self):
        if self._use_fallback:
            return
        self._web_view.page().runJavaScript("playRandomMotion()")

    def mouse_follow(self, x, y):
        if self._use_fallback:
            return
        js = f"setMouseFollow({x}, {y})"
        self._web_view.page().runJavaScript(js)

    def start_idle_timer(self, interval_ms=5000):
        if self._use_fallback:
            return
        js = f"startIdleTimer({interval_ms})"
        self._web_view.page().runJavaScript(js)

    def stop_idle_timer(self):
        if self._use_fallback:
            return
        self._web_view.page().runJavaScript("stopIdleTimer()")

    def set_scale(self, factor):
        if self._use_fallback:
            return
        js = f"setModelScale({factor})"
        self._web_view.page().runJavaScript(js)

    def _on_model_loaded(self, model_name):
        self.model_ready.emit(model_name)
        self.start_idle_timer()

    def _on_model_error(self, error_msg):
        self._show_fallback(f"模型加载失败\n{error_msg}")

    def _on_motion_started(self, group, name):
        pass

    def _on_motion_finished(self, group, name):
        self.motion_played.emit(name)


# 保持向后兼容
Live2DWidget = ModelWidget
