"""
3D 模型渲染组件
支持 Live2D 和 VRM 两种模型格式
通过 QWebEngineView 嵌入渲染网页

渲染模式：
1. 统一渲染（推荐）：使用 ModelManager + renderer.html
2. 独立渲染（降级）：每个角色使用自己的 index.html
"""

import os
import json

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QPoint, QEvent, QTimer
from PyQt5.QtGui import QColor, QMouseEvent
from PyQt5.QtWebEngineWidgets import QWebEngineView

from .live2d_bridge import Live2DBridge
from .model_manager import ModelManager, ModelType


CHARACTERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "characters")
)


class MouseTransparentOverlay(QWidget):
    """透明覆盖层，用于捕获鼠标事件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)

    def paintEvent(self, event):
        """不绘制任何内容，保持透明"""
        pass

    def mousePressEvent(self, event):
        """鼠标按下事件 - 传递给父窗口"""
        if self.parent():
            new_pos = self.mapToParent(event.pos())
            new_event = QMouseEvent(
                event.type(),
                new_pos,
                event.globalPos(),
                event.button(),
                event.buttons(),
                event.modifiers()
            )
            self.parent().mousePressEvent(new_event)
        event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 传递给父窗口"""
        if self.parent():
            new_pos = self.mapToParent(event.pos())
            new_event = QMouseEvent(
                event.type(),
                new_pos,
                event.globalPos(),
                event.button(),
                event.buttons(),
                event.modifiers()
            )
            self.parent().mouseMoveEvent(new_event)
        event.accept()

    def mouseReleaseEvent(self, event):
        """鼠标释放事件 - 传递给父窗口"""
        if self.parent():
            new_pos = self.mapToParent(event.pos())
            new_event = QMouseEvent(
                event.type(),
                new_pos,
                event.globalPos(),
                event.button(),
                event.buttons(),
                event.modifiers()
            )
            self.parent().mouseReleaseEvent(new_event)
        event.accept()

    def contextMenuEvent(self, event):
        """右键菜单事件 - 传递给父窗口"""
        if self.parent():
            parent = self.parent()
            while parent:
                if hasattr(parent, 'show_context_menu'):
                    parent.show_context_menu(event.globalPos())
                    event.accept()
                    return
                parent = parent.parent()
        event.accept()


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

        # 渲染模式：'unified' 或 'legacy'
        self._render_mode = "unified"
        self._model_manager = None
        self._unified_ready = False

        # 拖拽相关状态
        self._drag_start_pos = None
        self._is_dragging = False

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
        # 禁用 WebEngineView 的默认上下文菜单
        self._web_view.setContextMenuPolicy(Qt.NoContextMenu)

        # 创建透明覆盖层，用于捕获鼠标事件
        self._overlay = MouseTransparentOverlay(self)

        layout.addWidget(self._web_view)
        layout.addWidget(self._fallback_label)

    def _connect_bridge(self):
        self._bridge.model_loaded.connect(self._on_model_loaded)
        self._bridge.model_error.connect(self._on_model_error)
        self._bridge.motion_started.connect(self._on_motion_started)
        self._bridge.motion_finished.connect(self._on_motion_finished)

    def _init_model_manager(self):
        """初始化统一模型管理器"""
        print("[ModelWidget] _init_model_manager called", flush=True)
        if self._model_manager:
            print("[ModelWidget] ModelManager already exists", flush=True)
            return True

        try:
            print("[ModelWidget] Creating ModelManager...", flush=True)
            self._model_manager = ModelManager(self._web_view, self)

            # 连接信号
            self._model_manager.model_switched.connect(self._on_unified_model_loaded)
            self._model_manager.model_load_error.connect(self._on_unified_model_error)
            self._model_manager.engine_ready.connect(self._on_engine_ready)
            self._model_manager.state_changed.connect(self._on_manager_state_changed)

            # 预加载引擎
            print("[ModelWidget] Calling preload_engines...", flush=True)
            success = self._model_manager.preload_engines()
            if success:
                print("[ModelWidget] ModelManager initialized, preloading engines...", flush=True)
            else:
                print("[ModelWidget] ModelManager preload failed, will use legacy mode", flush=True)
                self._render_mode = "legacy"

            return success
        except Exception as e:
            print(f"[ModelWidget] ModelManager init error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            self._render_mode = "legacy"
            return False

    def resizeEvent(self, event):
        """窗口大小改变时，调整覆盖层大小"""
        super().resizeEvent(event)
        if hasattr(self, '_overlay'):
            self._overlay.setGeometry(self.rect())

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPos()
            self._is_dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 实现拖拽"""
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
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = None
            self._is_dragging = False
            event.accept()

    def contextMenuEvent(self, event):
        """右键菜单事件 - 传递给父窗口"""
        parent = self.parent()
        while parent:
            if hasattr(parent, 'show_context_menu'):
                parent.show_context_menu(event.globalPos())
                event.accept()
                return
            parent = parent.parent()
        super().contextMenuEvent(event)

    def load_character(self, character_id, profile=None):
        """加载角色模型"""
        self._character_id = character_id
        self._profile = profile

        # 获取模型类型
        appearance = profile.get("appearance", {}) if profile else {}
        self._model_type = appearance.get("styleType", "live2d")

        print(f"[ModelWidget] load_character: {character_id}", flush=True)
        print(f"[ModelWidget] styleType: {self._model_type}", flush=True)
        print(f"[ModelWidget] render_mode: {self._render_mode}", flush=True)

        # 首次加载时初始化 ModelManager
        if self._render_mode == "unified" and not self._model_manager:
            self._init_model_manager()

        # 根据渲染模式选择加载方式
        if self._render_mode == "unified" and self._model_manager:
            self._load_unified_mode(character_id, profile)
        else:
            self._load_legacy_mode(character_id, profile)

    def _load_unified_mode(self, character_id, profile):
        """使用统一渲染模式加载"""
        appearance = profile.get("appearance", {}) if profile else {}
        model_path = appearance.get("modelPath", "model/model.model3.json")

        # 构建完整路径
        full_path = os.path.join(CHARACTERS_DIR, character_id, model_path)
        if not os.path.exists(full_path):
            # 尝试去掉 assets/ 前缀
            if model_path.startswith("assets/"):
                model_path = model_path[len("assets/"):]
                full_path = os.path.join(CHARACTERS_DIR, character_id, model_path)

        if not os.path.exists(full_path):
            print(f"[ModelWidget] Model file not found: {full_path}")
            self._load_legacy_mode(character_id, profile)
            return

        # 构建相对路径（从 characters 目录开始）
        relative_path = os.path.join(character_id, model_path)

        print(f"[ModelWidget] Unified mode: loading {relative_path}")

        # 通过 ModelManager 加载
        success = self._model_manager.switch_model(relative_path, self._model_type)
        if not success:
            print("[ModelWidget] ModelManager switch failed, falling back to legacy")
            self._load_legacy_mode(character_id, profile)

    def _load_legacy_mode(self, character_id, profile):
        """使用独立渲染模式加载（降级方案）"""
        print(f"[ModelWidget] Legacy mode: loading {character_id}")

        # 查找角色的 index.html
        template_path = self._find_template(character_id)

        print(f"[ModelWidget] template_path: {template_path}")
        print(f"[ModelWidget] exists: {os.path.exists(template_path) if template_path else False}")

        if template_path and os.path.exists(template_path):
            # 设置 WebChannel 通信
            self._bridge.create_channel(self._web_view)

            # 断开旧的连接，避免重复
            try:
                self._web_view.loadFinished.disconnect()
            except TypeError:
                pass

            # 连接 loadFinished 信号，注入角色配置
            self._web_view.loadFinished.connect(self._on_page_loaded)

            # 加载页面
            abs_path = os.path.abspath(template_path)
            self._pending_url = QUrl.fromLocalFile(abs_path)
            print(f"[ModelWidget] Loading URL: {self._pending_url.toString()}")

            # 延迟加载新页面
            QTimer.singleShot(500, self._do_load_page)

            self._web_view.show()
            self._fallback_label.hide()
            self._use_fallback = False
        else:
            name = profile.get("name", character_id) if profile else character_id
            self._show_fallback(f"角色\n{name}\n等待模型文件...")
            self.fallback_visible.emit(True)

    def _do_load_page(self):
        """延迟加载页面"""
        if hasattr(self, '_pending_url'):
            print(f"[ModelWidget] _do_load: {self._pending_url.toString()}")
            self._web_view.load(self._pending_url)

    def _on_page_loaded(self, ok):
        """页面加载完成后注入角色配置（旧模式）"""
        current_url = self._web_view.url().toString()
        expected = self._pending_url.toString() if hasattr(self, '_pending_url') else ''
        print(f"[ModelWidget] page loaded: ok={ok}, current={current_url}, expected={expected}")

        if not ok or not self._profile:
            return

        if expected and current_url != expected:
            print(f"[ModelWidget] Ignoring stale loadFinished")
            return

        appearance = self._profile.get("appearance", {})
        name = self._profile.get("name", self._character_id)
        model_path = appearance.get("modelPath", "model/model.model3.json")
        style_type = appearance.get("styleType", "live2d")
        avatar = self._profile.get("preferences", {}).get("avatar", "🎀")

        # 将 modelPath 转换为相对于 index.html 的路径
        if model_path.startswith("assets/"):
            model_path = model_path[len("assets/"):]

        # 构建 JSON 配置
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
        """查找角色的 index.html"""
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
        """显示降级界面"""
        self._fallback_label.setText(text)
        self._fallback_label.show()
        self._web_view.hide()
        self._use_fallback = True
        self.fallback_visible.emit(True)

    # ========== 统一渲染模式回调 ==========

    def _on_unified_model_loaded(self, model_path):
        """统一模式：模型加载完成"""
        print(f"[ModelWidget] Unified model loaded: {model_path}")
        self._use_fallback = False
        self._fallback_label.hide()
        self._web_view.show()
        self.model_ready.emit(self._character_id)
        self.start_idle_timer()

    def _on_unified_model_error(self, model_path, error):
        """统一模式：模型加载失败"""
        print(f"[ModelWidget] Unified model error: {error}")
        # 降级到旧模式
        if self._profile:
            self._load_legacy_mode(self._character_id, self._profile)

    def _on_engine_ready(self, engine_type):
        """统一模式：引擎就绪"""
        print(f"[ModelWidget] Engine ready: {engine_type}")

    def _on_manager_state_changed(self, state, detail):
        """统一模式：状态变化"""
        print(f"[ModelWidget] Manager state: {state} - {detail}")

    # ========== 公共接口 ==========

    def play_motion(self, motion_name, group=""):
        """播放动作"""
        if self._use_fallback:
            return

        if self._render_mode == "unified" and self._model_manager:
            # 统一模式：通过 JS 调用
            js = f"if (window.playMotion) window.playMotion('{motion_name}', '{group}')"
            self._web_view.page().runJavaScript(js)
        else:
            # 旧模式：直接调用
            js = f"playMotion('{motion_name}', '{group}')"
            self._web_view.page().runJavaScript(js)

    def set_expression(self, expression_name):
        """设置表情"""
        if self._use_fallback:
            return

        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.setExpression) window.setExpression('{expression_name}')"
            self._web_view.page().runJavaScript(js)
        else:
            js = f"setExpression('{expression_name}')"
            self._web_view.page().runJavaScript(js)

    def set_random_motion(self):
        """播放随机动作"""
        if self._use_fallback:
            return

        if self._render_mode == "unified" and self._model_manager:
            self._web_view.page().runJavaScript("if (window.playRandomMotion) window.playRandomMotion()")
        else:
            self._web_view.page().runJavaScript("playRandomMotion()")

    def mouse_follow(self, x, y):
        """鼠标跟随"""
        if self._use_fallback:
            return

        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.setMouseFollow) window.setMouseFollow({x}, {y})"
            self._web_view.page().runJavaScript(js)
        else:
            js = f"setMouseFollow({x}, {y})"
            self._web_view.page().runJavaScript(js)

    def start_idle_timer(self, interval_ms=5000):
        """启动空闲定时器"""
        if self._use_fallback:
            return

        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.startIdleTimer) window.startIdleTimer({interval_ms})"
            self._web_view.page().runJavaScript(js)
        else:
            js = f"startIdleTimer({interval_ms})"
            self._web_view.page().runJavaScript(js)

    def stop_idle_timer(self):
        """停止空闲定时器"""
        if self._use_fallback:
            return

        if self._render_mode == "unified" and self._model_manager:
            self._web_view.page().runJavaScript("if (window.stopIdleTimer) window.stopIdleTimer()")
        else:
            self._web_view.page().runJavaScript("stopIdleTimer()")

    def set_scale(self, factor):
        """设置缩放"""
        if self._use_fallback:
            return

        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.setModelScale) window.setModelScale({factor})"
            self._web_view.page().runJavaScript(js)
        else:
            js = f"setModelScale({factor})"
            self._web_view.page().runJavaScript(js)

    def get_render_mode(self):
        """获取当前渲染模式"""
        return self._render_mode

    def get_manager_state(self):
        """获取 ModelManager 状态"""
        if self._model_manager:
            return self._model_manager.get_state()
        return None

    def _on_model_loaded(self, model_name):
        """模型加载完成（旧模式回调）"""
        self.model_ready.emit(model_name)
        self.start_idle_timer()

    def _on_model_error(self, error_msg):
        """模型加载失败（旧模式回调）"""
        self._show_fallback(f"模型加载失败\n{error_msg}")

    def _on_motion_started(self, group, name):
        """动作开始"""
        pass

    def _on_motion_finished(self, group, name):
        """动作结束"""
        self.motion_played.emit(name)

    def cleanup(self):
        """清理资源"""
        if self._model_manager:
            self._model_manager.cleanup()
        self._web_view.setHtml("")


# 保持向后兼容
Live2DWidget = ModelWidget
