"""
统一模型管理器
负责引擎预加载、模型切换、缓存管理、错误回传
"""

import os
import time
from enum import Enum
from collections import deque
from urllib.parse import quote

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, QTimer, QUrl
from PyQt5.QtWebChannel import QWebChannel


class ModelType(Enum):
    """模型类型枚举"""
    VRM = "vrm"
    LIVE2D = "live2d"


class ModelState(Enum):
    """模型状态枚举"""
    IDLE = "idle"
    LOADING = "loading"
    LOADED = "loaded"
    ERROR = "error"


class ModelManager(QObject):
    """
    统一的模型管理器
    - 启动时预加载 VRM 和 Live2D 引擎
    - 切换模型时只加载模型，不重新初始化引擎
    - 支持模型缓存，重复切换无需重新加载
    - 切换锁防止并发问题
    - 错误状态回传
    """

    # 信号
    model_switched = pyqtSignal(str)           # 模型切换完成 (model_path)
    model_load_error = pyqtSignal(str, str)    # 模型加载失败 (model_path, error)
    engine_ready = pyqtSignal(str)             # 引擎就绪 (engine_type)
    engine_error = pyqtSignal(str, str)        # 引擎初始化失败 (engine_type, error)
    state_changed = pyqtSignal(str, str)       # 状态变化 (state, detail)

    def __init__(self, web_view, parent=None):
        super().__init__(parent)
        self.web_view = web_view
        self.current_model = None
        self.current_type = None
        self.engines_ready = {
            ModelType.VRM: False,
            ModelType.LIVE2D: False
        }

        # 状态管理
        self.state = ModelState.IDLE
        self.is_switching = False
        self.load_start_time = None
        self.pending_switch = None  # 等待中的切换请求

        # 命令队列
        self._command_queue = deque()
        self._processing_command = False

        # 超时定时器
        self.load_timeout_timer = QTimer()
        self.load_timeout_timer.setSingleShot(True)
        self.load_timeout_timer.timeout.connect(self._on_load_timeout)

        # 就绪检查定时器
        self._ready_check_timer = QTimer()
        self._ready_check_timer.setSingleShot(True)
        self._ready_check_timer.timeout.connect(self._check_ready_timeout)

        # 内存监控定时器
        self._memory_monitor_timer = QTimer()
        self._memory_monitor_timer.timeout.connect(self._check_memory_pressure)
        self._memory_monitor_timer.start(30000)  # 每 30 秒检查一次

        # 缓存配置
        self._cache_max_size = 5
        self._cache_min_size = 2
        self._memory_pressure_threshold = 0.8  # 80% 内存使用率触发清理

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
        """预加载所有引擎 — 通过 Flask HTTP 服务加载，避免 file:/// 下 WebAssembly 限制"""
        print(f"[ModelManager] Loading renderer via HTTP", flush=True)
        self._set_state("loading", "Loading renderer page via HTTP...")

        # 断开旧连接
        try:
            self.web_view.loadFinished.disconnect()
        except TypeError:
            pass

        self.web_view.loadFinished.connect(self._on_page_loaded)
        self.web_view.load(QUrl("http://127.0.0.1:5000/static/renderer.html"))

        # 启动就绪检查超时（30 秒）
        self._ready_check_timer.start(30000)

        return True

    def _on_page_loaded(self, success):
        """页面加载完成后初始化引擎"""
        print(f"[ModelManager] _on_page_loaded: success={success}", flush=True)
        if not success:
            error_msg = "Renderer page load failed"
            print(f"[ModelManager] {error_msg}", flush=True)
            self._set_state("error", error_msg)
            self.engine_error.emit("all", error_msg)
            return

        print("[ModelManager] Page loaded, waiting for JS init...", flush=True)
        self._set_state("loading", "Waiting for JS initialization...")

        # 延迟初始化引擎，等待 JS 端 QWebChannel 初始化完成
        QTimer.singleShot(1000, self._start_engine_init)

    def _start_engine_init(self):
        """开始初始化引擎（延迟调用）"""
        print("[ModelManager] Starting engine initialization...", flush=True)
        self._set_state("loading", "Initializing engines...")

        # 先检查 JS 端是否就绪
        check_js = """
        (function() {
            return {
                modelManagerExists: !!window.modelManager,
                rendererExists: !!window.renderer,
                initEngineExists: !!window.initEngine
            };
        })()
        """
        self.web_view.page().runJavaScript(check_js, self._on_js_ready_check)

    def _on_js_ready_check(self, result):
        """JS 端就绪检查回调"""
        print(f"[ModelManager] JS ready check: {result}", flush=True)

        if not result or not result.get('modelManagerExists'):
            print("[ModelManager] Warning: modelManager not ready, retrying in 1s...", flush=True)
            QTimer.singleShot(1000, self._start_engine_init)
            return

        # JS 端就绪，按需初始化引擎
        print("[ModelManager] JS ready, initializing engines on demand...", flush=True)

        # JS 端就绪，按需初始化引擎
        print("[ModelManager] JS ready, initializing engines on demand...", flush=True)

        # 检查队列中是否有待处理的命令，只初始化需要的引擎
        if self._command_queue:
            # 只初始化队列中第一个命令需要的引擎
            _, first_type = self._command_queue[0]
            print(f"[ModelManager] Pre-initializing {first_type.value} engine for queued command", flush=True)
            self._init_engine(first_type)
            # 延迟初始化另一个引擎
            other_type = ModelType.LIVE2D if first_type == ModelType.VRM else ModelType.VRM
            QTimer.singleShot(2000, lambda: self._init_engine(other_type))
        else:
            # 没有待处理命令，初始化 VRM 引擎（默认）
            print(f"[ModelManager] Pre-initializing VRM engine (default)", flush=True)
            self._init_engine(ModelType.VRM)
            # 延迟初始化 Live2D 引擎
            QTimer.singleShot(2000, lambda: self._init_engine(ModelType.LIVE2D))

    def _init_engine(self, engine_type):
        """初始化指定引擎"""
        print(f"[ModelManager] _init_engine: {engine_type.value}", flush=True)

        # 使用回调方式处理异步函数，避免 Qt 不支持 async 返回值的问题
        js_code = f"""
        (function() {{
            console.log('[JS] Initializing {engine_type.value} engine...');
            window.initEngine('{engine_type.value}').then(function(result) {{
                console.log('[JS] {engine_type.value} result:', JSON.stringify(result));
                // 通过 QWebChannel 回传结果 — 必须检查 result.success
                if (window.modelManager) {{
                    if (result && result.success) {{
                        window.modelManager.onEngineReady('{engine_type.value}');
                    }} else {{
                        window.modelManager.onEngineError('{engine_type.value}',
                            result ? result.error : 'Unknown error');
                    }}
                }}
            }}).catch(function(error) {{
                console.error('[JS] {engine_type.value} error:', error.message);
                if (window.modelManager) {{
                    window.modelManager.onEngineError('{engine_type.value}', error.message);
                }}
            }});
            return true;
        }})()
        """
        print(f"[ModelManager] Running JS for {engine_type.value}...", flush=True)
        self.web_view.page().runJavaScript(js_code)

    def _on_engine_ready(self, engine_type, result):
        """引擎初始化完成回调"""
        print(f"[ModelManager] _on_engine_ready: {engine_type.value} - {result}", flush=True)
        if result and result.get('success'):
            self.engines_ready[engine_type] = True
            self.engine_ready.emit(engine_type.value)
            print(f"[ModelManager] {engine_type.value} engine ready", flush=True)

            # 检查是否所有引擎都就绪
            if all(self.engines_ready.values()):
                self._ready_check_timer.stop()
                self._set_state("ready", "All engines ready")
                self._process_next_command()
        else:
            error = result.get('error', 'Unknown error') if result else 'No result'
            print(f"[ModelManager] {engine_type.value} engine failed: {error}", flush=True)
            self.engine_error.emit(engine_type.value, error)

    def _check_ready_timeout(self):
        """引擎初始化超时"""
        not_ready = [t.value for t, ready in self.engines_ready.items() if not ready]
        error_msg = f"Engine init timeout: {', '.join(not_ready)}"
        print(f"[ModelManager] {error_msg}")
        self._set_state("error", error_msg)

        # 标记未就绪的引擎为错误
        for engine_type, ready in self.engines_ready.items():
            if not ready:
                self.engine_error.emit(engine_type.value, "Init timeout")

        # 超时后仍然尝试处理队列中的命令（降级到 legacy 模式）
        self._process_next_command()

    def switch_model(self, model_path, model_type):
        """
        切换模型（带队列和锁）

        Args:
            model_path: 模型文件路径
            model_type: 模型类型 ('vrm' 或 'live2d')
        """
        # 解析类型
        if isinstance(model_type, str):
            try:
                model_type = ModelType(model_type)
            except ValueError:
                error_msg = f"Invalid model type: {model_type}"
                print(f"[ModelManager] {error_msg}")
                self.model_load_error.emit(model_path, error_msg)
                return False

        # 如果正在切换，加入队列
        if self.is_switching:
            print(f"[ModelManager] Switch in progress, queuing: {model_path}")
            self._command_queue.clear()  # 清空旧队列，只保留最新请求
            self._command_queue.append((model_path, model_type))
            return True

        # 检查引擎是否就绪
        if not self.engines_ready.get(model_type):
            print(f"[ModelManager] {model_type.value} engine not ready, queuing...")
            self._command_queue.append((model_path, model_type))
            return True

        return self._execute_switch(model_path, model_type)

    def _execute_switch(self, model_path, model_type):
        """执行模型切换"""
        # 双重检查引擎就绪状态
        if not self.engines_ready.get(model_type):
            self.is_switching = False
            error_msg = f"{model_type.value} engine not ready"
            print(f"[ModelManager] {error_msg}", flush=True)
            self._set_state("error", error_msg)
            self.model_load_error.emit(model_path, error_msg)
            self._process_next_command()
            return False

        self.is_switching = True
        self.load_start_time = time.time()
        self._set_state("loading", f"Loading {model_type.value}: {os.path.basename(model_path)}")

        # 启动超时检测
        self.load_timeout_timer.start(60000)  # 60 秒超时（大模型文件 ~75MB）

        # 转换路径为绝对路径
        abs_model_path = self._resolve_model_path(model_path)

        print(f"[ModelManager] Switching to {model_type.value}: {abs_model_path}")

        # 使用回调方式处理异步函数
        js_code = f"""
        (function() {{
            console.log('[JS] Loading {model_type.value} model: {abs_model_path}');
            window.loadModel('{model_type.value}', '{abs_model_path}').then(function(result) {{
                console.log('[JS] Load result:', JSON.stringify(result));
                if (window.modelManager) {{
                    if (result && result.success) {{
                        window.modelManager.onModelLoaded('{model_path}', '{model_type.value}');
                    }} else {{
                        window.modelManager.onModelLoadError('{model_path}', '{model_type.value}', result ? result.error : 'Unknown error');
                    }}
                }}
            }}).catch(function(error) {{
                console.error('[JS] Load error:', error.message);
                if (window.modelManager) {{
                    window.modelManager.onModelLoadError('{model_path}', '{model_type.value}', error.message);
                }}
            }});
            return true;
        }})()
        """
        self.web_view.page().runJavaScript(js_code)

        return True

    def _process_next_command(self):
        """处理队列中的下一个命令"""
        print(f"[ModelManager] _process_next_command: queue_size={len(self._command_queue)}", flush=True)
        if self._command_queue:
            model_path, model_type = self._command_queue.popleft()
            print(f"[ModelManager] Processing queued command: {model_path}", flush=True)

            # 检查所需的引擎是否就绪，未就绪直接回传错误（避免经过 JS 的无效往返）
            if not self.engines_ready.get(model_type):
                error_msg = f"{model_type.value} engine not ready, cannot load model"
                print(f"[ModelManager] {error_msg}", flush=True)
                self._set_state("error", error_msg)
                # 直接通过信号通知错误（不需要经过 JS）
                self.model_load_error.emit(model_path, error_msg)
                return

            self._execute_switch(model_path, model_type)

    def _resolve_model_path(self, model_path):
        """将模型路径转换为 Flask HTTP URL（替代 file:///，避免 WebAssembly 限制）"""
        # model_path 格式为 "{character_id}/assets/model/{filename}"
        normalized = model_path.replace('\\', '/')
        if normalized.startswith('/'):
            normalized = normalized.lstrip('/')
        # URL 编码：中文 → UTF-8 百分号编码，空格 → %20，保留 / 分隔符
        encoded = quote(normalized, safe='/')
        return f'http://127.0.0.1:5000/characters/{encoded}'

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
            self._set_state("loaded", f"Loaded: {os.path.basename(model_path)}")
            self.model_switched.emit(model_path)
        else:
            error = result.get('error', 'Unknown error') if result else 'No result'
            print(f"[ModelManager] Model load failed: {error}")
            self._set_state("error", f"Load failed: {error}")
            self.model_load_error.emit(model_path, error)

        # 处理队列中的下一个命令
        self._process_next_command()

    def _on_load_timeout(self):
        """加载超时处理"""
        self.is_switching = False
        error_msg = "Load timeout (15s)"
        print(f"[ModelManager] {error_msg}")
        self._set_state("error", error_msg)
        self.model_load_error.emit(
            self.current_model or "unknown",
            error_msg
        )

        # 处理队列中的下一个命令
        self._process_next_command()

    def _set_state(self, state, detail=""):
        """设置状态并发射信号"""
        self.state = state
        self.state_changed.emit(state, detail)
        print(f"[ModelManager] State: {state} - {detail}")

    # ========== JS 回调接口 ==========

    @pyqtSlot(str, str)
    def onModelLoaded(self, model_path, model_type):
        """JS 端模型加载完成回调（备用）"""
        self._on_model_loaded(model_path, model_type, {'success': True})

    @pyqtSlot(str, str, str)
    def onModelLoadError(self, model_path, model_type, error):
        """JS 端模型加载失败回调（备用）"""
        self._on_model_loaded(model_path, model_type, {'success': False, 'error': error})

    @pyqtSlot(str)
    def onEngineReady(self, engine_type):
        """JS 端引擎就绪回调"""
        print(f"[ModelManager] onEngineReady called: {engine_type}", flush=True)
        try:
            et = ModelType(engine_type)
            self._on_engine_ready(et, {'success': True})
        except ValueError:
            print(f"[ModelManager] Unknown engine type: {engine_type}", flush=True)

    @pyqtSlot(str, str)
    def onEngineError(self, engine_type, error):
        """JS 端引擎错误回调"""
        print(f"[ModelManager] onEngineError called: {engine_type} - {error}", flush=True)
        # 标记该引擎为错误状态
        if engine_type in ['vrm', 'live2d']:
            try:
                et = ModelType(engine_type)
                self.engines_ready[et] = False
            except ValueError:
                pass
        # 发射引擎错误信号（WebEngineRenderer 监听后可触发降级）
        self.engine_error.emit(engine_type, error)
        self._process_next_command()

    # ========== 管理接口 ==========

    def get_cache_stats(self):
        """获取缓存统计"""
        js_code = "window.getCacheStats ? window.getCacheStats() : null;"
        return self.web_view.page().runJavaScript(js_code)

    def get_performance_report(self):
        """获取性能报告"""
        js_code = "window.getPerformanceReport ? window.getPerformanceReport() : null;"
        return self.web_view.page().runJavaScript(js_code)

    def get_log_history(self, level=None, limit=50):
        """获取 JS 端日志历史"""
        level_param = f"'{level}'" if level else "null"
        js_code = f"window.getLogHistory ? window.getLogHistory({level_param}, {limit}) : [];"
        return self.web_view.page().runJavaScript(js_code)

    def clear_log_history(self):
        """清除 JS 端日志历史"""
        js_code = "if (window.clearLogHistory) window.clearLogHistory();"
        self.web_view.page().runJavaScript(js_code)

    def clear_cache(self):
        """清空模型缓存"""
        js_code = "if (window.clearCache) window.clearCache();"
        self.web_view.page().runJavaScript(js_code)
        print("[ModelManager] Cache cleared")

    def set_cache_config(self, max_models=5):
        """设置缓存配置"""
        js_code = f"""
        if (window.renderer && window.renderer.modelCache) {{
            window.renderer.modelCache.maxSize = {max_models};
        }}
        """
        self.web_view.page().runJavaScript(js_code)
        print(f"[ModelManager] Cache max size set to {max_models}")

    def get_state(self):
        """获取当前状态"""
        return {
            'state': self.state,
            'current_model': self.current_model,
            'current_type': self.current_type.value if self.current_type else None,
            'engines_ready': {t.value: r for t, r in self.engines_ready.items()},
            'queue_size': len(self._command_queue),
            'is_switching': self.is_switching,
            'cache_max_size': self._cache_max_size
        }

    def _check_memory_pressure(self):
        """检查内存压力，动态调整缓存大小"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            usage_ratio = memory.percent / 100.0

            # 根据内存使用率调整缓存大小
            if usage_ratio > self._memory_pressure_threshold:
                # 内存压力大，减小缓存
                new_size = max(self._cache_min_size, self._cache_max_size - 1)
                if new_size != self._cache_max_size:
                    self._cache_max_size = new_size
                    self.set_cache_config(self._cache_max_size)
                    print(f"[ModelManager] Memory pressure high ({usage_ratio:.1%}), cache size: {self._cache_max_size}")
            elif usage_ratio < 0.6 and self._cache_max_size < 5:
                # 内存充足，可以增加缓存
                new_size = min(5, self._cache_max_size + 1)
                if new_size != self._cache_max_size:
                    self._cache_max_size = new_size
                    self.set_cache_config(self._cache_max_size)
                    print(f"[ModelManager] Memory OK ({usage_ratio:.1%}), cache size: {self._cache_max_size}")
        except ImportError:
            # psutil 未安装，跳过内存检查
            pass
        except Exception as e:
            print(f"[ModelManager] Memory check error: {e}")

    def cleanup(self):
        """清理所有资源"""
        self.load_timeout_timer.stop()
        self._ready_check_timer.stop()
        self._memory_monitor_timer.stop()
        self._command_queue.clear()

        js_code = "if (window.cleanup) window.cleanup();"
        self.web_view.page().runJavaScript(js_code)

        self._set_state("idle", "Cleaned up")
        print("[ModelManager] Cleanup complete")
