# Live2D 模型加载修复方案

## 一、问题描述

当前项目中，Live2D 类型的角色（如"胡桃"）在统一渲染模式下加载时总是失败，表现为模型无法显示，回退到 Fallback 占位界面。

---

## 二、根因分析（5 层）

### 2.1 第 1 层：URL 编码缺失 — 直接触发 404

**位置**: `gui/model_manager.py:325-331` `_resolve_model_path()`

```python
def _resolve_model_path(self, model_path):
    normalized = model_path.replace('\\', '/')
    return f'http://127.0.0.1:5000/characters/{normalized}'
    # 生成: http://127.0.0.1:5000/characters/胡桃/assets/model/Hu Tao.model3.json
```

路径中的中文（`胡桃`）和空格（`Hu Tao`）未做百分号编码。`pixi-live2d-display` 内部通过嵌入的 CubismFramework 直接拼接字符串来解析 model3.json 中引用的纹理路径：

```javascript
// pixi-live2d-display 内部拼接
texUrl = basePath + "Hu Tao.8192/texture_00.png"
// → 包含空格，XMLHttpRequest 发请求时编码可能不一致
```

当 PixiJS 请求 `Hu Tao.8192/texture_00.png`（含空格）时，如果编码处理不一致，导致 HTTP 404，3 张纹理全部加载失败，Live2D 初始化报错退出。

### 2.2 第 2 层：模型文件过大 — 超时与内存耗尽

胡桃模型的实际大小：

| 文件 | 大小 |
|------|------|
| `Hu Tao.moc3` | 8.7 MB |
| `Hu Tao.8192/texture_00.png` | 18.6 MB |
| `Hu Tao.8192/texture_01.png` | 18.7 MB |
| `Hu Tao.8192/texture_02.png` | 29.0 MB |
| **HTTP 下载总量** | **~75 MB** |
| **GPU 上传后 VRAM 占用** | **~80 MB（解码后 RGBA）** |

`ModelManager._execute_switch()` 设置的超时仅为 **15 秒**：

```python
self.load_timeout_timer.start(15000)  # 75MB 下载 + GPU 上传，15 秒不够
```

在集成显卡环境（与系统共享内存），PixiJS 需同时持有 3 个解码后的 Image 对象 + GPU 纹理副本，容易触发 `GL_OUT_OF_MEMORY`。

### 2.3 第 3 层：引擎初始化失败后无降级恢复

`static/js/unified_renderer.js` 的 `_initLive2DEngine()`：

```javascript
const app = new PIXI.Application({
    view: document.createElement('canvas'),
    width: container.clientWidth,   // ← 布局未完成时可能为 0
    height: container.clientHeight,  // ← 同上
    transparent: true,
    autoStart: false,
    resizeTo: container
});
```

如果 `#render-container` 尺寸为 0（QWebEngineView 布局尚未完成），`PIXI.Application` 可能创建失败。

发生失败后的错误传播链：

```
_initLive2DEngine 抛异常
  → this.engines.live2d 永远未设置
  → onEngineError('live2d', error)
  → Python ModelManager._process_next_command() 仍尝试执行 _execute_switch
  → JS _loadLive2DModel 检查 engine.ready → false
  → 二次失败，无降级路径
```

关键问题：**WebEngineRenderer 只在"模型文件不存在"时降级到 Legacy 模式，不在"引擎初始化失败"时降级**。

### 2.4 第 4 层：双重加载路径的 URL 格式不一致

| 路径 | 传入 `Live2DModel.from()` 的参数 |
|------|-------------------------------|
| **Legacy** (`characters/胡桃/assets/index.html`) | `model/Hu Tao.model3.json`（相对路径） |
| **Unified** (`static/renderer.html`) | `http://127.0.0.1:5000/characters/胡桃/assets/model/Hu Tao.model3.json`（绝对 URL） |

pixi-live2d-display 对相对路径和绝对 URL 的内部解析逻辑不同。绝对 URL 路径中的特殊字符依赖浏览器行为，相对路径由浏览器在页面基址上自动拼接。

### 2.5 第 5 层：SDK 版本历史遗留

```
static/sdk/
├── live2dcubismcore.min.js            (185KB, Cubism 4 Core, asm.js, "2019 Live2D")
├── live2dcubismcore.min.js.cubism5.bak (207KB, 曾改名而来)
├── cubism4.min.js                     (120KB, CubismFramework, renderer.html 未引用)
```

`.cubism5.bak` 文件说明历史上曾尝试 Cubism 5 然后恢复，不能完全排除 SDK 文件曾被部分覆盖。当前 Core 已验证导出完整 API（`Moc`, `Model`, `Utils`, `Logging`, `Version`），与 pixi-live2d-display 0.4.0 理论兼容。

---

## 三、修复方案（按优先级）

### P0 — URL 编码修复（1 行改动，置信度最高）

**文件**: `gui/model_manager.py`

**当前代码**（第 325-331 行）：
```python
def _resolve_model_path(self, model_path):
    normalized = model_path.replace('\\', '/')
    if normalized.startswith('/'):
        normalized = normalized.lstrip('/')
    return f'http://127.0.0.1:5000/characters/{normalized}'
```

**修改为**：
```python
from urllib.parse import quote

def _resolve_model_path(self, model_path):
    normalized = model_path.replace('\\', '/')
    if normalized.startswith('/'):
        normalized = normalized.lstrip('/')
    # URL 编码：空格 → %20，中文 → UTF-8 百分号编码
    encoded = quote(normalized, safe='/')
    return f'http://127.0.0.1:5000/characters/{encoded}'
```

**效果**: 生成的 URL 从 `.../胡桃/assets/model/Hu Tao.model3.json` 变为 `.../%E8%83%A1%E6%A1%83/assets/model/Hu%20Tao.model3.json`，确保各个 HTTP 客户端一致解析。

**验证方法**: 修复后观察 Python 控制台日志中打印的 URL 是否正确编码；在 Network 面板看纹理请求是否 200。

---

### P1 — 纹理压缩至合理大小（外部工具处理）

将 `Hu Tao.8192/` 下的 3 张纹理从原尺寸压缩。

**目标**：

| 纹理 | 当前大小 | 目标大小 |
|------|---------|---------|
| `texture_00.png` | 18.6 MB | ≤ 3 MB |
| `texture_01.png` | 18.7 MB | ≤ 3 MB |
| `texture_02.png` | 29.0 MB | ≤ 4 MB |
| **合计** | **~75 MB** | **≤ 10 MB** |

**方法**（选其一）：
1. 使用 [TinyPNG](https://tinypng.com/) 在线压缩（保持 PNG 格式，通常压缩 60-80%）
2. 使用 ImageMagick 命令行：`magick texture_00.png -resize 2048x2048 -quality 85 texture_00.png`
3. 将 8192 纹理降采样至 4096 或 2048（QWebEngineView 窗口一般 ≤ 400px，高分辨率纹理视觉收益极小）

---

### P1 — 引擎初始化增加 try/catch 与重试

**文件**: `static/js/unified_renderer.js`

**当前 `_initLive2DEngine`** 无 try/catch 保护。修改为：

```javascript
async _initLive2DEngine() {
    if (this.engines.live2d) {
        console.log('[Renderer] Live2D engine already initialized');
        return;
    }

    if (typeof PIXI === 'undefined') {
        throw new Error('PIXI not loaded');
    }

    if (!PIXI.live2d || !PIXI.live2d.Live2DModel) {
        await new Promise((resolve, reject) => {
            let attempts = 0;
            const check = setInterval(() => {
                attempts++;
                if (PIXI.live2d && PIXI.live2d.Live2DModel) {
                    clearInterval(check);
                    resolve();
                } else if (attempts > 100) {  // 延长至 10 秒
                    clearInterval(check);
                    reject(new Error('Live2DModel not available'));
                }
            }, 100);
        });
    }

    const container = document.getElementById('render-container');
    if (!container) throw new Error('render-container not found');

    // 确保容器有有效尺寸
    const w = container.clientWidth || 320;
    const h = container.clientHeight || 380;

    // 增加重试机制
    for (let retry = 0; retry < 3; retry++) {
        try {
            const app = new PIXI.Application({
                view: document.createElement('canvas'),
                width: w,
                height: h,
                transparent: true,
                autoStart: false,
                resizeTo: container
            });

            app.view.style.display = 'none';
            container.appendChild(app.view);

            this.engines.live2d = {
                app, canvas: app.view,
                currentModel: null, ready: true
            };

            console.log('[Renderer] Live2D engine initialized');
            return;  // 成功退出
        } catch (e) {
            console.warn(`[Renderer] Live2D init attempt ${retry + 1} failed:`, e.message);
            if (retry === 2) throw e;  // 最后一次仍失败则抛出
            await new Promise(r => setTimeout(r, 1000));  // 等 1 秒重试
        }
    }
}
```

---

### P2 — 引擎初始化失败后降级到 Legacy

**文件**: `gui/renderers/web_engine_renderer.py`

在 `_on_unified_model_error` 已存在降级逻辑，但需要补上"引擎未就绪时模型仍停留在队列"的情况。

在 `ModelManager.onEngineError`（`gui/model_manager.py` 第 399-404 行）中增加 Legacy 降级通知：

```python
@pyqtSlot(str, str)
def onEngineError(self, engine_type, error):
    print(f"[ModelManager] onEngineError called: {engine_type} - {error}", flush=True)
    # 标记该引擎为错误状态
    if engine_type in ['vrm', 'live2d']:
        try:
            et = ModelType(engine_type)
            self.engines_ready[et] = False  # 明确标记为未就绪
        except ValueError:
            pass
    # 发射引擎错误信号（WebEngineRenderer 监听后可触发降级）
    self.engine_error.emit(engine_type, error)
    # 不再处理队列（已在 _on_unified_model_error 降级）
```

同时在 `WebEngineRenderer._on_engine_ready` 的关联处，增加对 `engine_error` 信号的监听处理：当 Live2D 引擎失败且当前角色是 Live2D 类型时，自动降级到 Legacy 模式。

---

### P2 — 加载超时调整

**文件**: `gui/model_manager.py`

```python
# 当前（第 284 行）
self.load_timeout_timer.start(15000)  # 15 秒

# 改为
self.load_timeout_timer.start(60000)  # 60 秒（大模型场景）
```

---

## 四、修复后的预期效果

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 纹理加载成功率 | 0%（全部 404 或超时） | 100% |
| 首次加载时间 | 超时失败 | 10-30 秒（含 HTTP 下载） |
| 二次加载（缓存命中） | N/A | < 200ms |
| 引擎初始化失败恢复 | 卡死 | 自动降级 Legacy |
| 内存峰值 | N/A（未成功加载） | ~150-200MB |

---

## 五、验证步骤

1. 启动程序，切换到胡桃角色
2. 观察 Python 控制台日志，确认 `_resolve_model_path` 输出已编码的 URL
3. 确认日志中出现 `[Renderer] Live2D engine initialized` 或 `[ModelManager] Live2D engine ready`
4. 确认 `[ModelManager] Model loaded in X.XXXs (cache: false)` 日志出现
5. 胡桃模型正常显示在桌宠窗口中
6. 右键 → 对话，确认角色能正常回复
7. 切换到其他角色再切回胡桃，确认缓存命中（load time < 1s）

---

## 六、涉及文件清单

| 文件 | 改动类型 | 改动量 |
|------|---------|--------|
| `gui/model_manager.py` | P0 URL 编码 + P2 超时调整 | ~5 行 |
| `static/js/unified_renderer.js` | P1 try/catch + 重试 | ~20 行 |
| `gui/renderers/web_engine_renderer.py` | P2 降级逻辑 | ~10 行 |
| `characters/胡桃/assets/model/Hu Tao.8192/` | P1 纹理压缩 | 外部工具 |

---

*文档创建: 2026-05-20*
