"""
统一模型管理器
负责引擎预加载、模型切换、缓存管理
"""

import os
import time
from enum import Enum

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer, QUrl
from PyQt5.QtWebChannel import QWebChannel


class ModelType(Enum):
    """模型类型枚举"""
    VRM = "vrm"
    LIVE2D = "live2d"


class ModelManager(QObject):
    """
    统一的模型管理器
    - 启动时预加载 VRM 和 Live2D 引擎
    - 切换模型时只加载模型，不重新初始化引擎
    - 支持模型缓存，重复切换无需重新加载
    """

    # 信号
    model_switched = pyqtSignal(str)  # 模型切换完成
    model_load_error = pyqtSignal(str, str)  # 模型加载失败 (model_path, error)
    engine_ready = pyqtSignal(str)  # 引擎就绪 (engine_type)

    def __init__(self, web_view, parent=None):
        super().__init__(parent)
        self.web_view = web_view
        self.current_model = None
        self.current_type = None
        self.engines_ready = {
            ModelType.VRM: False,
            ModelType.LIVE2D: False
        }
        self.is_switching = False  # 切换锁
        self.load_start_time = None

        # 超时定时器
        self.load_timeout_timer = QTimer()
        self.load_timeout_timer.setSingleShot(True)
        self.load_timeout_timer.timeout.connect(self._on_load_timeout)

        # 设置 WebChannel
        self._setup_bridge()

    def _setup_bridge(self):
        """设置 Python-JS 通信桥"""
        self.channel = QWebChannel()
        self.channel.registerObject("modelManager", self)
        self.web_view.page().setWebChannel(self.channel)

    def get_renderer_path(self):
        """获取统一渲染页面路径"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(project_root, "static", "renderer.html")

    def preload_engines(self):
        """预加载所有引擎"""
        renderer_path = self.get_renderer_path()
        if not os.path.exists(renderer_path):
            print(f"[ModelManager] Renderer not found: {renderer_path}")
            return False

        print(f"[ModelManager] Loading renderer: {renderer_path}")
        self.web_view.loadFinished.connect(self._on_page_loaded)
        self.web_view.load(QUrl.fromLocalFile(renderer_path))
        return True

    def _on_page_loaded(self, success):
        """页面加载完成后初始化引擎"""
        if not success:
            print("[ModelManager] Page load failed")
            return

        print("[ModelManager] Page loaded, initializing engines...")

        # 异步初始化两个引擎
        self._init_engine(ModelType.VRM)
        self._init_engine(ModelType.LIVE2D)

    def _init_engine(self, engine_type):
        """初始化指定引擎"""
        js_code = f"""
        (async function() {{
            try {{
                const result = await window.initEngine('{engine_type.value}');
                return result;
            }} catch(e) {{
                return {{ success: false, error: e.message }};
            }}
        }})()
        """
        self.web_view.page().runJavaScript(
            js_code,
            lambda result: self._on_engine_ready(engine_type, result)
        )

    def _on_engine_ready(self, engine_type, result):
        """引擎初始化完成回调"""
        if result and result.get('success'):
            self.engines_ready[engine_type] = True
            self.engine_ready.emit(engine_type.value)
            print(f"[ModelManager] {engine_type.value} engine ready")
        else:
            error = result.get('error', 'Unknown error') if result else 'No result'
            print(f"[ModelManager] {engine_type.value} engine failed: {error}")

    def switch_model(self, model_path, model_type):
        """
        切换模型

        Args:
            model_path: 模型文件路径（相对于 index.html）
            model_type: 模型类型 ('vrm' 或 'live2d')
        """
        # 解析类型
        if isinstance(model_type, str):
            try:
                model_type = ModelType(model_type)
            except ValueError:
                print(f"[ModelManager] Invalid model type: {model_type}")
                return False

        # 检查切换锁
        if self.is_switching:
            print("[ModelManager] Switch in progress, skipping")
            return False

        # 检查引擎是否就绪
        if not self.engines_ready.get(model_type):
            print(f"[ModelManager] {model_type.value} engine not ready, waiting...")
            self.engine_ready.connect(
                lambda: self._do_switch(model_path, model_type)
            )
            return True

        return self._do_switch(model_path, model_type)

    def _do_switch(self, model_path, model_type):
        """执行模型切换"""
        self.is_switching = True
        self.load_start_time = time.time()

        # 启动超时检测
        self.load_timeout_timer.start(10000)  # 10 秒超时

        # 转换路径为绝对路径（相对于 renderer.html）
        abs_model_path = self._resolve_model_path(model_path)

        print(f"[ModelManager] Switching to {model_type.value}: {abs_model_path}")

        # 调用 JS 加载模型
        js_code = f"""
        (async function() {{
            try {{
                const result = await window.loadModel('{model_type.value}', '{abs_model_path}');
                return result;
            }} catch(e) {{
                return {{ success: false, error: e.message }};
            }}
        }})()
        """
        self.web_view.page().runJavaScript(
            js_code,
            lambda result: self._on_model_loaded(model_path, model_type, result)
        )

        return True

    def _resolve_model_path(self, model_path):
        """将路径转换为 file:/// URL 格式"""
        # 如果是相对路径，先转换为绝对路径
        if not os.path.isabs(model_path):
            # 获取 characters 目录
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            characters_dir = os.path.join(project_root, "characters")

            # 尝试多种路径组合
            candidates = [
                os.path.join(characters_dir, model_path),
                os.path.join(characters_dir, "assets", model_path),
                model_path
            ]

            for path in candidates:
                if os.path.exists(path):
                    model_path = os.path.abspath(path)
                    break

        # 将 Windows 路径转换为 file:/// URL
        if os.path.isabs(model_path):
            # 将反斜杠替换为正斜杠，并添加 file:/// 前缀
            url_path = model_path.replace('\\', '/')
            if url_path.startswith('C:'):
                # Windows 驱动器路径
                url_path = '/' + url_path
            return f'file:///{url_path}'

        return model_path

    def _on_model_loaded(self, model_path, model_type, result):
        """模型加载完成回调"""
        self.load_timeout_timer.stop()
        self.is_switching = False

        if result and result.get('success'):
            load_time = time.time() - self.load_start_time
            from_cache = result.get('fromCache', False)

            self.current_model = model_path
            self.current_type = model_type

            print(f"[ModelManager] Model loaded in {load_time:.3f}s (cache: {from_cache})")
            self.model_switched.emit(model_path)
        else:
            error = result.get('error', 'Unknown error') if result else 'No result'
            print(f"[ModelManager] Model load failed: {error}")
            self.model_load_error.emit(model_path, error)

    def _on_load_timeout(self):
        """加载超时处理"""
        self.is_switching = False
        print("[ModelManager] Model load timeout")
        self.model_load_error.emit(
            self.current_model or "unknown",
            "Load timeout (10s)"
        )

    @pyqtSlot(str, str)
    def onModelLoaded(self, model_path, model_type):
        """JS 端模型加载完成回调"""
        self._on_model_loaded(model_path, model_type, {'success': True})

    @pyqtSlot(str, str, str)
    def onModelLoadError(self, model_path, model_type, error):
        """JS 端模型加载失败回调"""
        self._on_model_loaded(model_path, model_type, {'success': False, 'error': error})

    def get_cache_stats(self):
        """获取缓存统计"""
        js_code = "window.getCacheStats();"
        return self.web_view.page().runJavaScript(js_code)

    def get_performance_report(self):
        """获取性能报告"""
        js_code = "window.getPerformanceReport();"
        return self.web_view.page().runJavaScript(js_code)

    def clear_cache(self):
        """清空模型缓存"""
        js_code = "window.clearCache();"
        self.web_view.page().runJavaScript(js_code)
        print("[ModelManager] Cache cleared")

    def set_cache_config(self, max_models=5):
        """设置缓存配置"""
        js_code = f"""
        window.renderer.modelCache.maxSize = {max_models};
        """
        self.web_view.page().runJavaScript(js_code)
        print(f"[ModelManager] Cache max size set to {max_models}")

    def cleanup(self):
        """清理所有资源"""
        self.load_timeout_timer.stop()
        js_code = "window.cleanup();"
        self.web_view.page().runJavaScript(js_code)
        print("[ModelManager] Cleanup complete")
