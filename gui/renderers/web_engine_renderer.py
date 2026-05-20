"""
WebEngine 渲染器 — 统一管理 Live2D 和 VRM
包含：QWebEngineView + ModelManager + Live2DBridge
"""

import os
import json

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView

from .base_renderer import BaseRenderer
from ..model_manager import ModelManager, ModelType
from ..live2d_bridge import Live2DBridge


class WebEngineRenderer(BaseRenderer):
    """Live2D / VRM 共用的 WebEngine 渲染器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widget = QWidget(parent)
        self._layout = QVBoxLayout(self._widget)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # WebEngineView
        self._web_view = QWebEngineView(self._widget)
        self._web_view.setContextMenuPolicy(Qt.NoContextMenu)
        self._layout.addWidget(self._web_view)

        # 降级标签
        self._fallback_label = QLabel(self._widget)
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

        # ModelManager
        self._model_manager = None

        # Live2DBridge（旧模式使用）
        self._bridge = Live2DBridge(self._widget)
        self._bridge.model_loaded.connect(self._on_bridge_model_loaded)
        self._bridge.model_error.connect(self._on_bridge_model_error)
        self._bridge.motion_finished.connect(self._on_bridge_motion_finished)

        # 状态
        self._render_mode = "unified"  # unified | legacy
        self._character_id = None
        self._profile = None
        self._use_fallback = False

    def load(self, character_id, profile, characters_dir):
        """加载角色模型"""
        self._character_id = character_id
        self._profile = profile
        self._use_fallback = False
        self._fallback_label.hide()
        self._web_view.show()

        appearance = profile.get("appearance", {}) if profile else {}
        model_type = appearance.get("styleType", "live2d")

        # 首次加载时初始化 ModelManager
        if self._render_mode == "unified" and not self._model_manager:
            self._init_model_manager()

        # 根据渲染模式选择加载方式
        if self._render_mode == "unified" and self._model_manager:
            return self._load_unified(character_id, profile, characters_dir)
        else:
            return self._load_legacy(character_id, profile, characters_dir)

    def _init_model_manager(self):
        """初始化统一模型管理器"""
        print("[WebEngineRenderer] _init_model_manager called", flush=True)
        if self._model_manager:
            return True

        try:
            self._model_manager = ModelManager(self._web_view, self._widget)
            self._model_manager.model_switched.connect(self._on_unified_model_loaded)
            self._model_manager.model_load_error.connect(self._on_unified_model_error)
            self._model_manager.engine_ready.connect(self._on_engine_ready)

            success = self._model_manager.preload_engines()
            if not success:
                print("[WebEngineRenderer] ModelManager preload failed, using legacy mode", flush=True)
                self._render_mode = "legacy"
            return success
        except Exception as e:
            print(f"[WebEngineRenderer] ModelManager init error: {e}", flush=True)
            self._render_mode = "legacy"
            return False

    def _load_unified(self, character_id, profile, characters_dir):
        """统一渲染模式加载"""
        appearance = profile.get("appearance", {})
        model_path = appearance.get("modelPath", "model/model.model3.json")
        model_type = appearance.get("styleType", "live2d")

        # 构建完整路径
        full_path = os.path.join(characters_dir, character_id, model_path)
        if not os.path.exists(full_path) and model_path.startswith("assets/"):
            model_path = model_path[len("assets/"):]
            full_path = os.path.join(characters_dir, character_id, model_path)

        if not os.path.exists(full_path):
            print(f"[WebEngineRenderer] Model file not found: {full_path}")
            return self._load_legacy(character_id, profile, characters_dir)

        relative_path = os.path.join(character_id, model_path)
        print(f"[WebEngineRenderer] Unified mode: loading {relative_path}")

        success = self._model_manager.switch_model(relative_path, model_type)
        if not success:
            print("[WebEngineRenderer] ModelManager switch failed, falling back to legacy")
            return self._load_legacy(character_id, profile, characters_dir)
        return True

    def _load_legacy(self, character_id, profile, characters_dir):
        """独立渲染模式加载（降级方案）"""
        print(f"[WebEngineRenderer] Legacy mode: loading {character_id}")

        template_path = self._find_template(character_id, characters_dir)
        if not template_path or not os.path.exists(template_path):
            name = profile.get("name", character_id) if profile else character_id
            self._show_fallback(f"角色\n{name}\n等待模型文件...")
            return False

        self._bridge.create_channel(self._web_view)

        try:
            self._web_view.loadFinished.disconnect()
        except TypeError:
            pass

        self._web_view.loadFinished.connect(self._on_page_loaded)
        abs_path = os.path.abspath(template_path)
        self._pending_url = QUrl.fromLocalFile(abs_path)
        QTimer.singleShot(500, self._do_load_page)
        return True

    def _do_load_page(self):
        if hasattr(self, '_pending_url'):
            self._web_view.load(self._pending_url)

    def _on_page_loaded(self, ok):
        """页面加载完成后注入角色配置"""
        current_url = self._web_view.url().toString()
        expected = self._pending_url.toString() if hasattr(self, '_pending_url') else ''

        if not ok or not self._profile:
            return
        if expected and current_url != expected:
            return

        appearance = self._profile.get("appearance", {})
        name = self._profile.get("name", self._character_id)
        model_path = appearance.get("modelPath", "model/model.model3.json")
        style_type = appearance.get("styleType", "live2d")
        avatar = self._profile.get("preferences", {}).get("avatar", "")

        if model_path.startswith("assets/"):
            model_path = model_path[len("assets/"):]

        config_json = json.dumps({
            "name": name,
            "avatar": avatar,
            "modelPath": model_path,
            "styleType": style_type,
            "scale": 1.0
        }, ensure_ascii=False)

        js = f"""
        try {{
            window._configInjected = true;
            updateConfig({config_json});
        }} catch(e) {{
            console.error('Config injection error:', e);
        }}
        """
        self._web_view.page().runJavaScript(js)

        # 注入角色级表情/动作映射
        self._inject_character_overrides()

    def _find_template(self, character_id, characters_dir):
        """查找角色的 index.html"""
        candidates = [
            os.path.join(characters_dir, character_id, "assets", "index.html"),
            os.path.join(characters_dir, character_id, "assets", "model", "index.html"),
            os.path.join(characters_dir, character_id, "index.html"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    def _inject_character_overrides(self):
        """将角色级 expressionMap/motionMap 注入到 JS 端"""
        if not self._profile:
            return

        appearance = self._profile.get("appearance", {})
        expression_map = appearance.get("expressionMap")
        motion_map = appearance.get("motionMap")

        if not expression_map and not motion_map:
            return

        expr_json = json.dumps(expression_map, ensure_ascii=False) if expression_map else "null"
        motion_json = json.dumps(motion_map, ensure_ascii=False) if motion_map else "null"

        js = f"""
        try {{
            if (window.setCharacterOverrides) {{
                window.setCharacterOverrides({expr_json}, {motion_json});
            }}
        }} catch(e) {{
            console.error('Override injection error:', e);
        }}
        """
        self._web_view.page().runJavaScript(js)

    def _show_fallback(self, text):
        self._fallback_label.setText(text)
        self._fallback_label.show()
        self._web_view.hide()
        self._use_fallback = True
        self.fallback_visible.emit(True)

    # ========== 统一模式回调 ==========

    def _on_unified_model_loaded(self, model_path):
        self._use_fallback = False
        self._fallback_label.hide()
        self._web_view.show()
        self.model_ready.emit(self._character_id)
        self._inject_character_overrides()
        self.start_idle_timer()

    def _on_unified_model_error(self, model_path, error):
        print(f"[WebEngineRenderer] Unified model error: {error}")
        if self._profile:
            self._load_legacy(self._character_id, self._profile,
                              os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/characters")

    def _on_engine_ready(self, engine_type):
        print(f"[WebEngineRenderer] Engine ready: {engine_type}")

    # ========== 旧模式回调 ==========

    def _on_bridge_model_loaded(self, model_name):
        self.model_ready.emit(model_name)
        self.start_idle_timer()

    def _on_bridge_model_error(self, error_msg):
        self._show_fallback(f"模型加载失败\n{error_msg}")

    def _on_bridge_motion_finished(self, group, name):
        self.motion_played.emit(name)

    # ========== 公共接口 ==========

    def play_motion(self, name, group=""):
        if self._use_fallback:
            return
        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.playMotion) window.playMotion('{name}', '{group}')"
        else:
            js = f"playMotion('{name}', '{group}')"
        self._web_view.page().runJavaScript(js)

    def set_expression(self, name):
        if self._use_fallback:
            return
        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.setExpression) window.setExpression('{name}')"
        else:
            js = f"setExpression('{name}')"
        self._web_view.page().runJavaScript(js)

    def set_random_motion(self):
        if self._use_fallback:
            return
        if self._render_mode == "unified" and self._model_manager:
            self._web_view.page().runJavaScript("if (window.playRandomMotion) window.playRandomMotion()")
        else:
            self._web_view.page().runJavaScript("playRandomMotion()")

    def mouse_follow(self, x, y):
        if self._use_fallback:
            return
        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.setMouseFollow) window.setMouseFollow({x}, {y})"
        else:
            js = f"setMouseFollow({x}, {y})"
        self._web_view.page().runJavaScript(js)

    def start_idle_timer(self, interval_ms=5000):
        if self._use_fallback:
            return
        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.startIdleTimer) window.startIdleTimer({interval_ms})"
        else:
            js = f"startIdleTimer({interval_ms})"
        self._web_view.page().runJavaScript(js)

    def stop_idle_timer(self):
        if self._use_fallback:
            return
        if self._render_mode == "unified" and self._model_manager:
            self._web_view.page().runJavaScript("if (window.stopIdleTimer) window.stopIdleTimer()")
        else:
            self._web_view.page().runJavaScript("stopIdleTimer()")

    def set_scale(self, factor):
        if self._use_fallback:
            return
        if self._render_mode == "unified" and self._model_manager:
            js = f"if (window.setModelScale) window.setModelScale({factor})"
        else:
            js = f"setModelScale({factor})"
        self._web_view.page().runJavaScript(js)

    def get_widget(self):
        return self._widget

    def get_cache_stats(self):
        if self._model_manager:
            return self._model_manager.get_cache_stats()
        return {"type": "webengine", "status": "model_manager_not_initialized"}

    def cleanup(self):
        if self._model_manager:
            self._model_manager.cleanup()
        self._web_view.setHtml("")

    def load_animations(self, anim_config, base_url):
        """加载动画文件到 JS 端 AnimationController"""
        if not anim_config:
            return

        config_json = json.dumps(anim_config, ensure_ascii=False)
        base_url_escaped = base_url.replace('\\', '/').replace("'", "\\'")

        js = f"""
        try {{
            if (window.loadAnimations) {{
                window.loadAnimations({config_json}, '{base_url_escaped}').then(function(count) {{
                    console.log('[Python] Animations loaded:', count);
                }});
            }}
        }} catch(e) {{
            console.error('Animation load error:', e);
        }}
        """
        self._web_view.page().runJavaScript(js)
