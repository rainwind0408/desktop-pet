# 桌面虚拟宠物项目 -- AI 开发指南

> 本文件供 AI 助手理解项目结构和开发规范。每次修改代码后，必须更新此文件并提交到本地 Git 仓库。

---

## 一、项目概述

这是一个 **Windows 桌面虚拟宠物应用**，用户可以与 AI 驱动的虚拟角色进行对话和互动。

**技术栈**: Python (PyQt5 + Flask) + Vue 3 + FAISS + SQLite

**核心能力**:
- 多角色系统（独立档案、记忆、音乐画像）
- LLM 对话（支持 12 家提供商）
- 永久记忆（向量检索 + 关键词匹配）
- 环境感知（时间/天气/纪念日）
- 媒体感知（音乐/视频播放检测）
- 行为决策（主动交互 + 防打扰）

---

## 二、目录结构

```
桌宠1/
├── main.py                    # 主入口，启动流程在此
├── requirements.txt           # Python 依赖
├── .gitignore                 # 版本控制规则
├── .env.example               # 环境变量模板
├── AI_GUIDE.md                # 本文件
├── 变更记录.md                 # 版本变更日志
├── 桌面虚拟宠物_完整技术方案.md  # 设计文档
│
├── core/                      # 核心业务模块
│   ├── __init__.py            # 导出: CharacterManager, MemorySystem, MusicAnalyzer
│   ├── character_manager.py   # 角色管理器（CRUD、切换、对话）
│   ├── memory_system.py       # 永久记忆系统（FAISS + SQLite + 加密）
│   └── music_analyzer.py      # 音乐数据分析（画像、情绪、Prompt）
│
├── sensors/                   # 感知模块
│   ├── __init__.py            # 导出: EnvironmentSensor, MediaSensor, MusicTracker
│   ├── environment_sensor.py  # 时空环境感知（时间/天气/纪念日）
│   ├── media_sensor.py        # 多模态媒体感知（SMTC/窗口检测）
│   ├── music_tracker.py       # 音乐播放记录（SQLite 存储）
│   └── environment_cache.json # 天气缓存
│
├── decision/                  # 决策模块
│   ├── __init__.py            # 导出: InteractionDecider
│   └── interaction_decider.py # 交互决策引擎（规则 + LLM）
│
├── api/                       # REST API 模块
│   ├── __init__.py            # 导出: APIServer
│   └── server.py              # Flask API 服务（22 个端点）
│
├── gui/                       # PyQt5 桌面窗口模块
│   ├── __init__.py            # 导出: PetWindow, ModelWidget, Live2DBridge
│   ├── pet_window.py          # 主窗口 + 对话框 + 设置框
│   ├── model_widget.py        # 3D 模型渲染组件（Live2D/VRM）
│   └── live2d_bridge.py       # Python-JS 双向通信桥接
│
├── llm/                       # LLM 接口模块
│   ├── __init__.py            # 导出: Provider 类, LLMFactory, PROVIDER_PRESETS
│   ├── provider.py            # LLM 提供者实现（OpenAI兼容 + Anthropic）
│   ├── factory.py             # LLM 工厂 + 配置管理
│   ├── llm_config.json        # 主配置（当前提供商 key）
│   └── config/                # 各提供商独立配置（含 API Key，已 gitignore）
│
├── characters/                # 角色数据目录
│   ├── example_character/     # 示例角色
│   │   ├── profile.json       # 角色档案
│   │   ├── memory_metadata.db # 记忆数据库
│   │   ├── memory_index.faiss # 向量索引
│   │   ├── music_history.db   # 音乐播放历史
│   │   ├── music_profile.json # 音乐画像
│   │   ├── 记忆摘要.txt        # 人类可读摘要
│   │   └── assets/
│   │       ├── index.html     # 渲染页面
│   │       └── model/
│   │           ├── character.vrm  # VRM 模型文件
│   │           └── textures/     # 纹理
│   └── 永雏塔菲/              # 另一个角色（同结构）
│
├── frontend/                  # Vue 3 Web 前端（开发中）
│   ├── package.json
│   ├── vite.config.js         # 端口 3000，代理 /api -> localhost:5000
│   └── src/
│       ├── main.js            # 入口
│       ├── App.vue            # 根组件
│       ├── api/index.js       # API 封装
│       ├── components/
│       │   └── CharacterSwitcher.vue
│       └── views/
│           ├── HomeView.vue
│           └── SettingsView.vue
│
└── 人物模型/                   # 模型资源（已 gitignore）
```

---

## 三、核心模块详解

### 3.1 角色管理器 (`core/character_manager.py`)

**类**: `CharacterManager`

**职责**: 角色 CRUD、切换、AI 对话

**对话流程** (`chat_with_character`):
```
用户输入
  ↓
组装 system prompt = 性格 + 环境感知 + 记忆召回 + 音乐画像
  ↓
调用 LLM Provider.chat(messages)
  ↓
异步存储对话到记忆系统
  ↓
返回回复
```

**关键依赖注入**:
- `set_memory_system(memory_system)`
- `set_environment_sensor(environment_sensor)`
- `set_music_analyzer(music_analyzer)`
- `set_llm_provider(llm_provider)`

---

### 3.2 记忆系统 (`core/memory_system.py`)

**核心类**:
- `SQLiteConnectionPool` -- 连接池，WAL 模式
- `EmbeddingProvider` -- 向量化接口（API + n-gram 降级）
- `MemoryEncryptor` -- Fernet AES 加密，自动检测敏感信息
- `MemorySystem` -- 主类

**记忆检索算法**:
```
综合得分 = 向量相似度 × 0.5
         + 时间衰减 × 0.2
         + 重要性 × 0.2
         + 关键词匹配 × 0.1
```

**重要性评分范围**: 0.2（问候）~ 0.9（生日/纪念日）

**FAISS 索引升级**: 数据量 > 1000 时自动从 `IndexFlatIP` 切换到 `IndexIVFFlat`

---

### 3.3 LLM 模块 (`llm/`)

**支持的提供商** (12个):
OpenAI, DeepSeek, Qwen, Zhipu, Moonshot, Anthropic, Baidu, MiniMax, StepFun, Doubao, Ollama, Custom

**配置管理**:
- `llm/llm_config.json` -- 只存当前提供商 key
- `llm/config/{provider}.json` -- 每个提供商独立配置（API Key 等）
- 切换提供商时自动保存/加载，无需重复填写 API Key

**热重载**: 通过 `/api/config/llm` PUT 接口更新配置后自动重新初始化 LLM

---

### 3.4 感知模块 (`sensors/`)

**环境感知** (`EnvironmentSensor`):
- 时间: 时段（清晨/上午/中午/下午/傍晚/深夜）、季节
- 天气: wttr.in → Open-Meteo → 本地缓存（三级降级）
- 纪念日: 基于 `firstMetTimestamp` 计算相识天数
- IP 定位: ip-api.com 自动获取用户城市

**媒体感知** (`MediaSensor`):
- Windows SMTC API 获取当前播放（标题/艺术家/专辑/平台）
- 前台窗口检测（20+ 视频/音乐应用）
- 3 秒轮询，状态变化触发回调

**音乐追踪** (`MusicTracker`):
- SQLite 存储播放历史，30 秒去重
- 统计: Top 歌曲/艺术家、播放时段、最爱平台
- 自动清理 90 天前旧记录

---

### 3.5 决策引擎 (`decision/interaction_decider.py`)

**规则驱动**:
| 情境 | 反应 | 优先级 |
|------|------|--------|
| 用户空闲 > 30 分钟 | 主动问候 | 3（高） |
| 深夜 + 听歌 | 安静陪伴 | 2 |
| 深夜 + 未听歌 | 提醒休息 | 2 |
| 快节奏音乐 | 快速点头 | 1 |
| 恐怖视频 | 害怕反应 | 2 |
| 早晨 | 问候 | 1 |

**冷却机制**: 600 秒，优先级 ≥ 3 可突破

**LLM 行为总结**: 每 7 分钟分析行为日志，生成互动建议

---

### 3.6 GUI 模块 (`gui/`)

**主窗口** (`PetWindow`):
- 无边框、透明背景、置顶
- 左键拖拽，右键菜单（对话/设置/退出）
- 系统托盘支持

**模型渲染** (`ModelWidget`):
- QWebEngineView 嵌入 HTML
- 支持 Live2D 和 VRM 两种格式
- 页面加载后通过 `runJavaScript` 注入角色配置（`updateConfig()`）
- 降级: 无模型时显示占位标签

**Python-JS 桥接** (`Live2DBridge`):
- QWebChannel 双向通信
- 信号: model_loaded, motion_started/finished, tap_received, drag_*

---

### 3.7 API 端点清单 (`api/server.py`)

**角色管理**:
- `GET /api/characters` -- 角色列表
- `GET /api/character/current` -- 当前角色
- `POST /api/character/switch` -- 切换角色
- `POST /api/character/create` -- 创建角色
- `DELETE /api/character/<id>` -- 删除角色
- `POST /api/character/save` -- 保存档案
- `POST /api/character/chat` -- AI 对话

**环境/记忆/交互**:
- `GET /api/environment` -- 环境上下文
- `POST /api/environment/weather/refresh` -- 刷新天气
- `GET /api/memory/stats` -- 记忆统计
- `POST /api/memory/summary` -- 生成摘要
- `POST /api/memory/rebuild` -- 重建索引
- `GET /api/interaction/decide` -- 交互决策
- `POST /api/interaction/media` -- 更新媒体状态
- `GET /api/interaction/status` -- 决策器状态

**配置**:
- `GET /api/config/llm` -- 获取 LLM 配置
- `PUT /api/config/llm` -- 更新 LLM 配置（热重载）
- `GET /api/config/llm/provider` -- 指定提供商配置

**系统**:
- `GET /api/health` -- 健康检查
- `GET /api/media/state` -- 媒体状态

---

## 四、模块依赖关系

```
main.py
  ├─→ CharacterManager
  │     ├─→ MemorySystem (EmbeddingProvider, MemoryEncryptor, SQLiteConnectionPool)
  │     ├─→ EnvironmentSensor
  │     ├─→ MusicAnalyzer ← MusicTracker
  │     └─→ LLMProvider
  │
  ├─→ MediaSensor ──callback──→ InteractionDecider.update_media_state()
  │                  callback──→ MusicTracker.record_play()
  │
  ├─→ InteractionDecider
  │     ├─→ EnvironmentSensor
  │     └─→ LLMProvider (行为总结)
  │
  ├─→ APIServer
  │     └─→ CharacterManager, EnvironmentSensor, MemorySystem,
  │         InteractionDecider, MediaSensor, LLMFactory
  │
  └─→ PetWindow
        ├─→ ModelWidget ← Live2DBridge (QWebChannel)
        ├─→ ChatDialog → API (HTTP)
        └─→ SettingsDialog → API (HTTP)
```

---

## 五、启动流程 (`main.py`)

```
1. 创建 CharacterManager
2. 加载 LLM 配置 (llm_config.json → provider config)
3. 初始化 MemorySystem
4. 初始化 EnvironmentSensor, InteractionDecider, MediaSensor
5. 设置音乐系统延迟初始化（角色切换时按需创建）
6. 初始化 LLM Provider → 注入 CharacterManager
7. 启动 MediaSensor 后台轮询 → 联动 InteractionDecider + MusicTracker
8. 启动 InteractionDecider 后台总结线程
9. 启动 Flask API (127.0.0.1:5000) 守护线程
10. 创建 PyQt5 App + PetWindow，自动切换到第一个角色
11. 注册退出清理 (memory_system.cleanup + music cleanup)
```

---

## 六、关键设计模式

### 6.1 对话 Prompt 组装

```python
system_content = personality_prompt          # 角色性格
system_content += environment_prompt         # 时间/天气/纪念日
system_content += memory_prompt              # 长期记忆召回
system_content += music_prompt               # 音乐偏好
messages = [{"role": "system", "content": system_content}, {"role": "user", "content": input}]
```

### 6.2 模型渲染配置注入

```python
# model_widget.py
def _on_page_loaded(self, ok):
    config = {"name": ..., "modelPath": ..., "styleType": ...}
    js = f"window._configInjected = true; updateConfig({json.dumps(config)});"
    self._web_view.page().runJavaScript(js)
```

### 6.3 天气多级降级

```
wttr.in (主) → Open-Meteo (备) → 本地缓存 (兜底)
```

### 6.4 记忆加密

自动检测敏感内容（密码/手机号/地址/身份证/银行卡），使用 Fernet AES-128-CBC 加密存储。

---

## 七、开发规范

### 7.1 修改代码后的必做操作

每次修改代码后，**必须**执行以下步骤：

1. **更新本文件** (`AI_GUIDE.md`)
   - 如果修改了模块功能、接口、依赖关系，更新对应章节
   - 如果新增了模块或文件，补充目录结构和说明
   - 保持文档与代码同步

2. **提交到本地 Git 仓库**
   ```bash
   cd E:\桌宠1
   git add -A
   git commit -m "描述性提交信息"
   ```

3. **更新变更记录** (`变更记录.md`)
   - 在文件顶部添加新条目
   - 格式参考已有条目（日期 + 变更类型 + 变更内容 + 修改文件）

### 7.2 提交信息规范

```
类型: 简短描述

- 具体修改点 1
- 具体修改点 2
```

类型包括: 功能增强、Bug 修复、代码重构、性能优化、文档更新

### 7.3 角色数据结构

每个角色的目录结构:
```
characters/{角色名}/
├── profile.json           # 必需：角色档案
├── memory_metadata.db     # 自动生成：记忆数据库
├── memory_index.faiss     # 自动生成：向量索引
├── music_history.db       # 自动生成：播放历史
├── music_profile.json     # 自动生成：音乐画像
├── 记忆摘要.txt            # 自动生成：人类可读摘要
└── assets/
    ├── index.html         # 必需：渲染页面
    └── model/
        ├── character.vrm  # 模型文件（Live2D 或 VRM）
        └── textures/      # 纹理文件
```

### 7.4 profile.json 格式

```json
{
  "characterId": "唯一ID",
  "name": "显示名称",
  "description": "角色描述",
  "firstMetTimestamp": null,
  "appearance": {
    "modelPath": "assets/model/character.vrm",
    "styleType": "vrm"  // "live2d" 或 "vrm"
  },
  "personality": {
    "prompt": "AI 人设提示词...",
    "tone": "soft",
    "style": "cute"
  },
  "preferences": {
    "voice": "default_01",
    "theme": "pink"
  }
}
```

---

## 八、常见修改场景

### 8.1 添加新角色

1. 创建 `characters/{角色名}/` 目录
2. 编写 `profile.json`
3. 放置模型文件到 `assets/model/`
4. 复制 `index.html` 模板到 `assets/`
5. 启动程序，角色自动出现在列表中

### 8.2 切换 LLM 提供商

1. 通过设置界面选择提供商
2. 填写 API Key
3. 点击保存 → 自动热重载

或通过 API:
```bash
curl -X PUT http://127.0.0.1:5000/api/config/llm \
  -H "Content-Type: application/json" \
  -d '{"provider":"deepseek","model":"deepseek-v4-flash","api_key":"sk-xxx"}'
```

### 8.3 修改角色性格

编辑 `characters/{角色名}/profile.json` 中的 `personality.prompt` 字段。

### 8.4 添加新的交互规则

编辑 `decision/interaction_decider.py` 中的 `_rule_based_decide` 方法。

---

## 九、已知限制

1. **Windows 平台**: 媒体感知依赖 Win32 API 和 SMTC，仅支持 Windows
2. **CDN 依赖**: 模型渲染依赖 CDN 加载 Three.js/Live2D SDK，需要网络
3. **WebEngine 网络警告**: 启动时可能有 `Network service crashed` 日志，不影响功能
4. **Embedding 降级**: 无 API Key 时使用 n-gram 哈希，检索精度降低
5. **单机部署**: 当前设计为单机运行，不支持多设备同步

---

## 十、环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `QWEN_API_KEY` | 通义千问 API Key | - |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `WEATHER_API_KEY` | 天气 API Key（可选） | - |

优先级: 环境变量 > `llm/config/{provider}.json` > 预设默认值

---

*本文件最后更新: 2026-05-19*
