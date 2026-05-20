# Spritesheet 2D 渲染集成方案

> 基于现有项目架构，详细分析如何将 Spritesheet 2D 渲染作为第三种渲染方式集成到系统中。

---

## 一、现有渲染架构分析

### 1.1 当前渲染流程

```
ModelWidget.load_character(character_id, profile)
  │
  ├── styleType == "vrm" | "live2d"
  │     ├── 统一模式 → ModelManager → renderer.html → JS 引擎
  │     └── 降级模式 → 角色独立 index.html
  │
  └── styleType == "sprite"  ← 【待新增】
        └── SpriteWidget → QLabel → QPixmap (Python 端渲染)
```

### 1.2 核心组件职责

| 组件 | 文件 | 职责 | 渲染方式 |
|------|------|------|----------|
| `ModelWidget` | `gui/model_widget.py` | 渲染容器，统一公共接口 | 持有子组件 |
| `ModelManager` | `gui/model_manager.py` | JS 引擎管理、缓存、队列 | QWebEngineView |
| `Live2DBridge` | `gui/live2d_bridge.py` | JS ↔ Python 桥接 | QWebChannel |
| `PetWindow` | `gui/pet_window.py` | 主窗口，调用 ModelWidget | 嵌入 ModelWidget |

### 1.3 ModelWidget 公共接口（必须统一实现）

```python
play_motion(motion_name, group="")   # 播放动作
set_expression(expression_name)       # 设置表情
set_random_motion()                   # 随机动作
mouse_follow(x, y)                    # 鼠标跟随
start_idle_timer(interval_ms)         # 启动空闲定时器
stop_idle_timer()                     # 停止空闲定时器
set_scale(factor)                     # 缩放
load_character(character_id, profile) # 加载角色
cleanup()                             # 清理资源
```

### 1.4 信号接口（必须统一发射）

```python
model_ready = pyqtSignal(str)      # 模型就绪
motion_played = pyqtSignal(str)    # 动作播放完成
fallback_visible = pyqtSignal(bool) # 降级界面可见
```

---

## 二、集成策略

### 2.1 核心思路

**Spritesheet 模式完全绕过 QWebEngineView**，使用 `QLabel + QPixmap` 在 Python 端直接渲染。这意味着：

- 不需要 `ModelManager`（JS 引擎管理）
- 不需要 `Live2DBridge`（JS 桥接）
- 不需要 `renderer.html` / `unified_renderer.js`
- 只需要 `Pillow`（图片裁剪）+ `PyQt5`（已有）

### 2.2 架构变化

```
修改前:
ModelWidget
  ├── QWebEngineView (始终创建)
  ├── ModelManager (始终创建)
  ├── Live2DBridge (始终创建)
  └── _fallback_label

修改后:
ModelWidget
  ├── QWebEngineView (sprite 模式不创建)
  ├── ModelManager (sprite 模式不创建)
  ├── Live2DBridge (sprite 模式不创建)
  ├── SpriteWidget (sprite 模式创建)  ← 新增
  └── _fallback_label
```

### 2.3 修改范围

| 文件 | 改动类型 | 改动内容 |
|------|----------|----------|
| `gui/sprite_widget.py` | **新增** | Spritesheet 渲染组件 |
| `gui/model_widget.py` | **修改** | 增加 sprite 模式分支 |
| `gui/model_manager.py` | 不变 | — |
| `gui/live2d_bridge.py` | 不变 | — |
| `gui/__init__.py` | **修改** | 导出 SpriteWidget |
| `gui/pet_window.py` | 不变 | — |
| `requirements.txt` | **修改** | 添加 `pillow` |
| `characters/*/profile.json` | **修改** | styleType 新增 `"sprite"` |

---

## 三、详细设计

### 3.1 新增 `gui/sprite_widget.py`

```python
"""
Spritesheet 2D 渲染组件
通过 QLabel + QPixmap 直接渲染帧动画，不依赖 QWebEngineView
"""

import os
import time
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt5.QtGui import QPixmap, QMouseEvent

try:
    from PIL import Image, ImageQt
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class SpriteWidget(QWidget):
    """Spritesheet 2D 渲染组件"""

    # 信号（与 ModelWidget 保持一致）
    model_ready = pyqtSignal(str)
    motion_played = pyqtSignal(str)

    # 状态 → 行号映射（兼容 InteractionDecider 输出）
    DEFAULT_STATE_MAP = {
        # 基础状态
        "idle": 0, "walk": 1, "run": 2, "jump": 3,
        "wave": 4, "fail": 5, "wait": 6, "review": 7, "work": 8,
        # 兼容 InteractionDecider 输出的动画名
        "nod_fast": 2,      # 快速点头 → 跑步行（节奏快）
        "nod_gentle": 1,    # 轻柔点头 → 走路行（节奏慢）
        "sleepy": 6,        # 困倦 → 等待行
        "sit_quietly": 0,   # 安静坐着 → 待机行
        "scared": 5,        # 害怕 → 失败行
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._spritesheet = None       # QPixmap
        self._frame_w = 0
        self._frame_h = 0
        self._cols = 9
        self._rows = 8
        self._speed = 100              # ms per frame
        self._current_state = "idle"
        self._current_row = 0
        self._current_frame = 0
        self._state_map = dict(self.DEFAULT_STATE_MAP)
        self._idle_timer = None
        self._is_playing = False

        # UI
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        # 动画定时器
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._next_frame)

    def load_spritesheet(self, image_path, config=None):
        """
        加载 Spritesheet 并开始播放

        Args:
            image_path: PNG 图片路径
            config: dict, 可选配置
                - columns: 列数 (默认 9)
                - rows: 行数 (默认 8)
                - frameWidth: 帧宽度 (可选，不指定则自动计算)
                - frameHeight: 帧高度 (可选)
                - defaultSpeed: 默认帧率 ms (默认 100)
                - stateMap: 状态映射 dict (可选，合并到默认映射)
                - transparentColor: 透明色 hex (可选)
        """
        if not os.path.exists(image_path):
            print(f"[SpriteWidget] Spritesheet not found: {image_path}")
            return False

        config = config or {}
        self._cols = config.get("columns", 9)
        self._rows = config.get("rows", 8)
        self._speed = config.get("defaultSpeed", 100)

        # 合并自定义状态映射
        custom_map = config.get("stateMap", {})
        self._state_map.update(custom_map)

        # 加载图片
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            print(f"[SpriteWidget] Failed to load image: {image_path}")
            return False

        # 处理透明色
        transparent = config.get("transparentColor")
        if transparent:
            # 用 Pillow 处理透明色转换
            if HAS_PIL:
                pil_img = Image.open(image_path).convert("RGBA")
                # 将指定颜色设为透明
                # ... (透明色处理逻辑)
                pixmap = QPixmap.fromImage(ImageQt.ImageQt(pil_img))

        self._spritesheet = pixmap
        self._frame_w = config.get("frameWidth", pixmap.width() // self._cols)
        self._frame_h = config.get("frameHeight", pixmap.height() // self._rows)

        # 开始播放待机动画
        self._play_state("idle")
        self.model_ready.emit("sprite")
        return True

    def play_motion(self, name, group=""):
        """播放指定动作（兼容 ModelWidget 接口）"""
        self._play_state(name)

    def set_expression(self, name):
        """设置表情（Spritesheet 模式下映射为动作）"""
        self._play_state(name)

    def set_random_motion(self):
        """播放随机动作"""
        import random
        states = list(self._state_map.keys())
        self._play_state(random.choice(states))

    def mouse_follow(self, x, y):
        """鼠标跟随（Spritesheet 模式下可选择忽略或做简单偏移）"""
        pass  # 2D Spritesheet 不支持眼神跟随

    def start_idle_timer(self, interval_ms=5000):
        """启动空闲随机动作定时器"""
        self.stop_idle_timer()
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._idle_action)
        self._idle_timer.start(interval_ms)

    def stop_idle_timer(self):
        """停止空闲定时器"""
        if self._idle_timer:
            self._idle_timer.stop()
            self._idle_timer = None

    def set_scale(self, factor):
        """缩放（重新渲染当前帧）"""
        if self._spritesheet:
            self._render_current_frame(scale=factor)

    def cleanup(self):
        """清理资源"""
        self._anim_timer.stop()
        self.stop_idle_timer()
        self._spritesheet = None
        self._label.clear()

    # ========== 内部方法 ==========

    def _play_state(self, state):
        """播放指定状态的动画"""
        if not self._spritesheet:
            return

        row = self._state_map.get(state, 0)
        if row >= self._rows:
            row = 0

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

        # 一轮动画结束，发射信号
        if self._current_frame == 0:
            self.motion_played.emit(self._current_state)

    def _render_current_frame(self, scale=1.0):
        """渲染当前帧到 QLabel"""
        if not self._spritesheet:
            return

        x = self._current_frame * self._frame_w
        y = self._current_row * self._frame_h
        frame = self._spritesheet.copy(x, y, self._frame_w, self._frame_h)

        if scale != 1.0:
            new_w = int(frame.width() * scale)
            new_h = int(frame.height() * scale)
            frame = frame.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        self._label.setPixmap(frame)

    def _idle_action(self):
        """空闲时随机切换动作"""
        import random
        idle_states = ["idle", "wait", "review"]
        self._play_state(random.choice(idle_states))
```

### 3.2 修改 `gui/model_widget.py`

改动点共 **5 处**：

#### 改动 1: 导入 SpriteWidget

```python
# 文件头部新增
from .sprite_widget import SpriteWidget
```

#### 改动 2: `__init__` 增加 sprite 模式状态

```python
class ModelWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._character_id = None
        self._profile = None
        self._bridge = Live2DBridge(self)
        self._use_fallback = False
        self._model_type = "live2d"  # 'live2d' | 'vrm' | 'sprite'

        # 渲染模式：'unified' 或 'legacy'
        self._render_mode = "unified"
        self._model_manager = None
        self._unified_ready = False

        # sprite 模式组件
        self._sprite_widget = None  # 新增

        # 拖拽相关状态
        self._drag_start_pos = None
        self._is_dragging = False

        self._init_ui()
        self._connect_bridge()
```

#### 改动 3: `_init_ui` 改为延迟创建 WebEngineView

```python
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

    # WebEngineView 延迟到需要时创建（sprite 模式不需要）
    self._web_view = None
    self._web_view_layout_slot = layout  # 保存 layout 引用

    # 透明覆盖层
    self._overlay = MouseTransparentOverlay(self)

    layout.addWidget(self._fallback_label)
```

#### 改动 4: `load_character` 增加 sprite 分支（核心改动）

```python
def load_character(self, character_id, profile=None):
    """加载角色模型"""
    self._character_id = character_id
    self._profile = profile

    # 获取模型类型
    appearance = profile.get("appearance", {}) if profile else {}
    self._model_type = appearance.get("styleType", "live2d")

    print(f"[ModelWidget] load_character: {character_id}", flush=True)
    print(f[flush=True)
    print(f"[ModelWidget] styleType: {self._model_type}", flush=True)

    # ===== 新增: sprite 模式 =====
    if self._model_type == "sprite":
        self._load_sprite_mode(character_id, profile)
        return

    # 确保 WebEngineView 已创建
    self._ensure_web_view()

    # 首次加载时初始化 ModelManager
    if self._render_mode == "unified" and not self._model_manager:
        self._init_model_manager()

    # 根据渲染模式选择加载方式
    if self._render_mode == "unified" and self._model_manager:
        self._load_unified_mode(character_id, profile)
    else:
        self._load_legacy_mode(character_id, profile)
```

#### 改动 5: 新增 `_load_sprite_mode` 和 `_ensure_web_view`

```python
def _ensure_web_view(self):
    """确保 QWebEngineView 已创建（sprite 模式跳过）"""
    if self._web_view is not None:
        return

    self._web_view = QWebEngineView(self)
    self._web_view.setContextMenuPolicy(Qt.NoContextMenu)

    # 插入到 layout 中（在 fallback_label 之前）
    self._web_view_layout_slot.insertWidget(0, self._web_view)

    # 连接 bridge
    self._connect_bridge()

def _load_sprite_mode(self, character_id, profile):
    """使用 Spritesheet 2D 模式加载"""
    print(f"[ModelWidget] Sprite mode: loading {character_id}")

    # 隐藏 WebEngineView（如果存在）
    if self._web_view:
        self._web_view.hide()

    # 清理旧的 sprite widget
    if self._sprite_widget:
        self._sprite_widget.cleanup()
        self._sprite_widget.deleteLater()

    # 创建新的 sprite widget
    self._sprite_widget = SpriteWidget(self)
    self._sprite_widget.model_ready.connect(
        lambda cid: self.model_ready.emit(cid)
    )
    self._sprite_widget.motion_played.connect(
        lambda name: self.motion_played.emit(name)
    )

    # 加入布局
    self.layout().addWidget(self._sprite_widget)
    self._sprite_widget.show()

    # 构建 spritesheet 路径
    appearance = profile.get("appearance", {})
    model_path = appearance.get("modelPath", "assets/spritesheet.png")
    if model_path.startswith("assets/"):
        model_path = model_path[len("assets/"):]

    sheet_path = os.path.join(CHARACTERS_DIR, character_id, model_path)
    sprite_config = appearance.get("spriteConfig", {})

    # 加载
    success = self._sprite_widget.load_spritesheet(sheet_path, sprite_config)
    if not success:
        name = profile.get("name", character_id)
        self._show_fallback(f"角色\n{name}\nSpritesheet 加载失败...")

    self._fallback_label.hide()
    self._use_fallback = False
```

#### 改动 6: 公共接口增加 sprite 分支

```python
def play_motion(self, motion_name, group=""):
    """播放动作"""
    if self._model_type == "sprite" and self._sprite_widget:
        self._sprite_widget.play_motion(motion_name, group)
        return

    if self._use_fallback:
        return
    # ... 原有逻辑不变

def set_expression(self, expression_name):
    """设置表情"""
    if self._model_type == "sprite" and self._sprite_widget:
        self._sprite_widget.set_expression(expression_name)
        return
    # ... 原有逻辑不变

def set_random_motion(self):
    if self._model_type == "sprite" and self._sprite_widget:
        self._sprite_widget.set_random_motion()
        return
    # ... 原有逻辑不变

def mouse_follow(self, x, y):
    if self._model_type == "sprite":
        return  # sprite 模式不支持
    # ... 原有逻辑不变

def start_idle_timer(self, interval_ms=5000):
    if self._model_type == "sprite" and self._sprite_widget:
        self._sprite_widget.start_idle_timer(interval_ms)
        return
    # ... 原有逻辑不变

def stop_idle_timer(self):
    if self._model_type == "sprite" and self._sprite_widget:
        self._sprite_widget.stop_idle_timer()
        return
    # ... 原有逻辑不变

def set_scale(self, factor):
    if self._model_type == "sprite" and self._sprite_widget:
        self._sprite_widget.set_scale(factor)
        return
    # ... 原有逻辑不变

def cleanup(self):
    """清理资源"""
    if self._sprite_widget:
        self._sprite_widget.cleanup()
    if self._model_manager:
        self._model_manager.cleanup()
    if self._web_view:
        self._web_view.setHtml("")
```

### 3.3 修改 `gui/__init__.py`

```python
from .pet_window import PetWindow
from .model_widget import ModelWidget
from .model_manager import ModelManager, ModelType
from .live2d_bridge import Live2DBridge
from .sprite_widget import SpriteWidget  # 新增

Live2DWidget = ModelWidget

__all__ = [
    'PetWindow',
    'ModelWidget',
    'ModelManager',
    'ModelType',
    'Live2DWidget',
    'Live2DBridge',
    'SpriteWidget',  # 新增
]
```

### 3.4 修改 `requirements.txt`

```
# 新增
pillow
```

### 3.5 角色 profile.json 配置

```json
{
  "characterId": "my_sprite_pet",
  "name": "像素宠物",
  "appearance": {
    "modelPath": "assets/spritesheet.png",
    "styleType": "sprite",
    "spriteConfig": {
      "columns": 9,
      "rows": 8,
      "defaultSpeed": 100,
      "transparentColor": "#000000",
      "stateMap": {
        "idle": 0,
        "walk": 1,
        "run": 2,
        "jump": 3,
        "wave": 4,
        "fail": 5,
        "wait": 6,
        "review": 7,
        "work": 8
      }
    }
  },
  "personality": {
    "prompt": "你是一只可爱的像素宠物..."
  }
}
```

---

## 四、数据流对比

### 4.1 Live2D/VRM 模式数据流

```
PetWindow
  → ModelWidget.play_motion("wave")
    → runJavaScript("window.playMotion('wave')")
      → JS: pixi-live2d-display / three-vrm 执行动画
        → QWebChannel 回调 motion_finished
          → ModelWidget.motion_played.emit("wave")
```

### 4.2 Sprite 模式数据流

```
PetWindow
  → ModelWidget.play_motion("wave")
    → SpriteWidget.play_motion("wave")
      → _play_state("wave") → row=4
        → QTimer 驱动 _next_frame() 逐帧播放
          → QPixmap.copy() 裁剪当前帧
            → QLabel.setPixmap() 显示
              → 一轮结束 → motion_played.emit("wave")
```

**关键区别**: Sprite 模式完全在 Python 进程内完成，无 JS 引擎、无 IPC、无 WebChannel。

---

## 五、状态映射兼容性

InteractionDecider 输出的动画名 → SpriteWidget 状态映射：

| InteractionDecider 动画 | 含义 | Sprite 行号 | 映射理由 |
|------------------------|------|-------------|----------|
| `wave` | 挥手打招呼 | 4 | 直接对应 |
| `nod_fast` | 快速点头 | 2 (run) | 节奏快，用跑步帧 |
| `nod_gentle` | 轻柔点头 | 1 (walk) | 节奏慢，用走路帧 |
| `sleepy` | 困倦 | 6 (wait) | 等待态最安静 |
| `sit_quietly` | 安静坐着 | 0 (idle) | 待机态 |
| `scared` | 害怕 | 5 (fail) | 失败/惊吓态 |

用户可通过 `spriteConfig.stateMap` 自定义覆盖这些映射。

---

## 六、性能对比

| 指标 | Live2D/VRM | Sprite 2D |
|------|-----------|-----------|
| 首次加载 | ~500ms (引擎预加载后) | **~10ms** (QPixmap 加载) |
| 重复切换 | ~50ms (缓存命中) | **~5ms** (重新加载 PNG) |
| 内存占用 | ~50-150MB (WebEngine + GPU) | **~5-20MB** (QPixmap) |
| CPU 占用 | 低 (GPU 渲染) | 低 (QPixmap blit) |
| 依赖 | Three.js/PixiJS SDK (本地) | **无** (仅 Pillow) |
| 资源大小 | 5-50MB/角色 | **0.5-2MB/角色** |

---

## 七、测试验证清单

### 7.1 基础功能

- [ ] `styleType: "sprite"` 角色能正常加载显示
- [ ] Spritesheet 帧动画正常播放
- [ ] 状态切换（idle → wave → idle）流畅
- [ ] 窗口拖拽正常工作
- [ ] 缩放功能正常

### 7.2 兼容性

- [ ] `styleType: "vrm"` 角色不受影响
- [ ] `styleType: "live2d"` 角色不受影响
- [ ] 三种类型角色可正常切换
- [ ] InteractionDecider 输出的所有动画名都能正确映射

### 7.3 降级与容错

- [ ] Spritesheet 文件不存在时显示降级界面
- [ ] Pillow 未安装时有明确错误提示
- [ ] spriteConfig 缺失时使用默认值

### 7.4 性能

- [ ] Sprite 模式启动不创建 QWebEngineView
- [ ] 内存占用低于 Live2D/VRM 模式
- [ ] 切换到 sprite 角色后 WebEngineView 资源释放

---

## 八、实施优先级与工作量

| 阶段 | 内容 | 工作量 |
|------|------|--------|
| 1 | 创建 `SpriteWidget` 核心组件 | 2h |
| 2 | 修改 `ModelWidget` 集成 sprite 分支 | 1.5h |
| 3 | 修改 `__init__.py`、`requirements.txt` | 0.5h |
| 4 | 制作测试用 Spritesheet + config | 1h |
| 5 | 测试验证 + 修复问题 | 1h |
| **合计** | | **~6h** |

---

*本文档最后更新: 2026-05-20*
