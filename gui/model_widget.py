"""
3D 模型渲染组件
支持 Live2D 和 VRM 两种模型格式
通过 QWebEngineView 嵌入渲染网页

优化版本：使用 ModelManager 实现引擎预加载和模型缓存
"""

import os

from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QUrl, pyqtSignal, QPoint
from PyQt5.QtGui import QColor, QMouseEvent
from PyQt5.QtWebEngineWidgets import QWebEngineView

from .live2d_bridge import Live2DBridge
from .model_manager import ModelManager, ModelType


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

        # 使用新的 ModelManager
        self._model_manager = None

        self._init_ui()
        self._connect_bridge()
        self._init_model_manager()

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
        # 在 ModelWidget 上安装事件过滤器，监听所有子部件事件
        self.installEventFilter(self)
        # 同时也安装到 web_view 上
        self._web_view.installEventFilter(self)

        layout.addWidget(self._web_view)
        layout.addWidget(self._fallback_label)

        # 拖拽相关状态
        self._drag_start_pos = None
        self._is_dragging = False

    def _connect_bridge(self):
        self._bridge.model_loaded.connect(self._on_model_loaded)
        self._bridge.model_error.connect(self._on_model_error)
        self._bridge.motion_started.connect(self._on_motion_started)
        self._bridge.motion_finished.connect(self._on_motion_finished)

    def eventFilter(self, obj, event):
        """事件过滤器：拦截鼠标事件"""
        from PyQt5.QtCore import QEvent
        # 只处理鼠标事件
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease):
            # 检查事件是否在 ModelWidget 区域内
            if self.rect().contains(self.mapFromGlobal(event.globalPos())):
                if event.type() == QEvent.MouseButtonPress:
                    self._handle_mouse_press(event)
                    return True
                elif event.type() == QEvent.MouseMove:
                    self._handle_mouse_move(event)
                    return True
                elif event.type() == QEvent.MouseButtonRelease:
                    self._handle_mouse_release(event)
                    return True
        return super().eventFilter(obj, event)

    def _handle_mouse_press(self, event):
        """处理鼠标按下"""
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = event.globalPos()
            self._is_dragging = False

    def _handle_mouse_move(self, event):
        """处理鼠标移动 - 实现拖拽"""
        if event.buttons() & Qt.LeftButton and self._drag_start_pos:
            delta = event.globalPos() - self._drag_start_pos
            if not self._is_dragging and (abs(delta.x()) > 3 or abs(delta.y()) > 3):
                self._is_dragging = True

            if self._is_dragging:
                window = self.window()
                if window:
                    window.move(window.pos() + delta)
                self._drag_start_pos = event.globalPos()

    def _handle_mouse_release(self, event):
        """处理鼠标释放"""
        if event.button() == Qt.LeftButton:
            self._drag_start_pos = None
            self._is_dragging = False

    def _init_model_manager(self):
        """初始化模型管理器"""
        self._model_manager = ModelManager(self._web_view, self)

        # 连接信号
        self._model_manager.model_switched.connect(self._on_model_switched)
        self._model_manager.model_load_error.connect(self._on_model_load_error)
        self._model_manager.engine_ready.connect(self._on_engine_ready)

        # 预加载引擎
        print("[ModelWidget] Preloading engines...")
        self._model_manager.preload_engines()

    def _on_model_switched(self, model_path):
        """模型切换完成"""
        print(f"[ModelWidget] Model switched: {model_path}")
        self._use_fallback = False
        self._fallback_label.hide()
        self._web_view.show()
        self.model_ready.emit(self._character_id or model_path)

    def _on_model_load_error(self, model_path, error):
        """模型加载失败"""
        print(f"[ModelWidget] Model load error: {error}")
        self._show_fallback(f"模型加载失败\n{error}")

    def _on_engine_ready(self, engine_type):
        """引擎就绪"""
        print(f"[ModelWidget] Engine ready: {engine_type}")

    def load_character(self, character_id, profile=None):
        self._character_id = character_id
        self._profile = profile

        # 获取模型类型
        appearance = profile.get("appearance", {}) if profile else {}
        self._model_type = appearance.get("styleType", "live2d")

        # 获取模型路径
        model_path = appearance.get("modelPath", "")

        print(f"[ModelWidget] load_character: {character_id}", flush=True)
        print(f"[ModelWidget] styleType: {self._model_type}", flush=True)
        print(f"[ModelWidget] modelPath: {model_path}", flush=True)

        if not model_path:
            name = profile.get("name", character_id) if profile else character_id
            self._show_fallback(f"角色\n{name}\n等待模型文件...")
            self.fallback_visible.emit(True)
            return

        # 转换路径
        if model_path.startswith("assets/"):
            model_path = model_path[len("assets/"):]

        # 构建完整模型路径
        full_model_path = os.path.join(
            CHARACTERS_DIR, character_id, "assets", model_path
        )

        if not os.path.exists(full_model_path):
            print(f"[ModelWidget] Model file not found: {full_model_path}")
            name = profile.get("name", character_id) if profile else character_id
            self._show_fallback(f"角色\n{name}\n模型文件不存在...")
            self.fallback_visible.emit(True)
            return

        # 使用 ModelManager 加载模型
        abs_model_path = os.path.abspath(full_model_path)
        print(f"[ModelWidget] Switching to model: {abs_model_path}")

        success = self._model_manager.switch_model(abs_model_path, self._model_type)
        if success:
            self._web_view.show()
            self._fallback_label.hide()
            self._use_fallback = False
        else:
            self._show_fallback("模型切换失败")

    def _show_fallback(self, text):
        self._fallback_label.setText(text)
        self._fallback_label.show()
        self._web_view.hide()
        self._use_fallback = True
        self.fallback_visible.emit(True)

    def play_motion(self, motion_name, group=""):
        if self._use_fallback:
            return
        # 处理默认值
        motion_group = group if group else 'TapBody'
        # 通过 JS 接口播放动作
        js = f"""
        (function() {{
            if (window.renderer && window.renderer.currentEngineType === 'vrm') {{
                const engine = window.renderer.engines.vrm;
                if (engine && engine.currentModel) {{
                    // VRM 表情
                    if (engine.currentModel.expressionManager) {{
                        const expressionMap = {{
                            'happy': 'happy',
                            'joy': 'happy',
                            'surprised': 'surprised',
                            'sad': 'sad',
                            'upset': 'angry'
                        }};
                        const expression = expressionMap['{motion_name}'];
                        if (expression) {{
                            engine.currentModel.expressionManager.setValue(expression, 1.0);
                            setTimeout(() => {{
                                engine.currentModel.expressionManager.setValue(expression, 0);
                            }}, 1500);
                        }}
                    }}
                }}
            }} else if (window.renderer && window.renderer.currentEngineType === 'live2d') {{
                const engine = window.renderer.engines.live2d;
                if (engine && engine.currentModel) {{
                    try {{
                        engine.currentModel.motion('{motion_group}');
                    }} catch(e) {{
                        console.log('Live2D motion error:', e.message);
                    }}
                }}
            }}
        }})()
        """
        self._web_view.page().runJavaScript(js)

    def set_expression(self, expression_name):
        if self._use_fallback:
            return
        js = f"""
        (function() {{
            if (window.renderer && window.renderer.engines.vrm) {{
                const engine = window.renderer.engines.vrm;
                if (engine && engine.currentModel && engine.currentModel.expressionManager) {{
                    engine.currentModel.expressionManager.setValue('{expression_name}', 1.0);
                    setTimeout(() => {{
                        engine.currentModel.expressionManager.setValue('{expression_name}', 0);
                    }}, 1500);
                }}
            }}
        }})()
        """
        self._web_view.page().runJavaScript(js)

    def set_random_motion(self):
        if self._use_fallback:
            return
        self.play_motion('idle')

    def mouse_follow(self, x, y):
        if self._use_fallback:
            return
        js = f"""
        (function() {{
            if (window.renderer && window.renderer.engines.vrm) {{
                const engine = window.renderer.engines.vrm;
                if (engine && engine.currentModel && engine.currentModel.lookAt) {{
                    const targetX = ({x} / window.innerWidth - 0.5) * 2;
                    const targetY = ({y} / window.innerHeight - 0.5) * 2;
                    engine.currentModel.lookAt.target.position.set(targetX * 0.5, targetY * 0.5 + 1.3, 2);
                }}
            }}
        }})()
        """
        self._web_view.page().runJavaScript(js)

    def start_idle_timer(self, interval_ms=5000):
        if self._use_fallback:
            return
        # 由 JS 端管理空闲定时器
        pass

    def stop_idle_timer(self):
        if self._use_fallback:
            return
        # 由 JS 端管理空闲定时器
        pass

    def set_scale(self, factor):
        if self._use_fallback:
            return
        js = f"""
        (function() {{
            if (window.renderer) {{
                if (window.renderer.engines.vrm && window.renderer.engines.vrm.currentModel) {{
                    window.renderer.engines.vrm.currentModel.scene.scale.set({factor}, {factor}, {factor});
                }}
                if (window.renderer.engines.live2d && window.renderer.engines.live2d.currentModel) {{
                    window.renderer.engines.live2d.currentModel.scale.set({factor});
                }}
            }}
        }})()
        """
        self._web_view.page().runJavaScript(js)

    def _on_model_loaded(self, model_name):
        """兼容旧版 Live2DBridge 回调"""
        self.model_ready.emit(model_name)

    def _on_model_error(self, error_msg):
        """兼容旧版 Live2DBridge 回调"""
        self._show_fallback(f"模型加载失败\n{error_msg}")

    def _on_motion_started(self, group, name):
        pass

    def _on_motion_finished(self, group, name):
        self.motion_played.emit(name)

    def get_cache_stats(self):
        """获取缓存统计"""
        if self._model_manager:
            return self._model_manager.get_cache_stats()
        return None

    def get_performance_report(self):
        """获取性能报告"""
        if self._model_manager:
            return self._model_manager.get_performance_report()
        return None

    def clear_cache(self):
        """清空缓存"""
        if self._model_manager:
            self._model_manager.clear_cache()

    def cleanup(self):
        """清理资源"""
        if self._model_manager:
            self._model_manager.cleanup()


# 保持向后兼容
Live2DWidget = ModelWidget
