# 🐾 桌面虚拟宠物

一个 **Windows 桌面虚拟宠物**应用，支持 AI 驱动的虚拟角色对话、永久记忆、环境感知和音乐互动。

![Tech Stack](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![GUI](https://img.shields.io/badge/GUI-PyQt5-green)
![API](https://img.shields.io/badge/API-Flask-lightgrey)
![LLM](https://img.shields.io/badge/LLM-12%20Providers-orange)

---

## ✨ 功能特性

| 特性 | 说明 |
|------|------|
| 🎭 **多角色系统** | 独立档案、记忆、音乐画像，自由切换 |
| 💬 **AI 对话** | 支持 12 家 LLM 提供商（DeepSeek / OpenAI / Anthropic / 通义千问 / 智谱 / 月之暗面 等） |
| 🧠 **永久记忆** | FAISS 向量检索 + SQLite 存储，自动加密敏感信息，多维度评分检索 |
| 🌤 **环境感知** | 时间季节、实时天气（三级降级）、相识纪念日、IP 定位 |
| 🎵 **音乐感知** | Windows SMTC 检测当前播放，记录收听历史，分析音乐偏好 |
| 🤖 **主动交互** | 规则驱动决策引擎：空闲问候、深夜提醒、音乐响应、视频检测 |
| 🎨 **多模型渲染** | 支持 Live2D / VRM / Spritesheet 三种渲染方式，引擎预加载，LRU 缓存 |
| ⚙ **便捷设置** | 系统托盘、右键菜单、可视化配置界面 |

---

## 🏗 项目架构

```
桌宠1/
├── main.py                    # 主入口
├── core/                      # 核心业务
│   ├── character_manager.py   # 角色管理器
│   ├── memory_system.py       # 永久记忆系统
│   └── music_analyzer.py      # 音乐数据分析
├── sensors/                   # 感知模块
│   ├── environment_sensor.py  # 环境感知
│   ├── media_sensor.py        # 媒体感知
│   └── music_tracker.py       # 音乐追踪
├── decision/                  # 决策引擎
│   └── interaction_decider.py # 交互决策
├── api/                       # REST API
│   └── server.py              # Flask 服务（22 个端点）
├── gui/                       # 桌面窗口
│   ├── pet_window.py          # 主窗口 + 对话框
│   ├── model_widget.py        # 渲染路由层
│   ├── model_manager.py       # 模型管理器
│   └── renderers/             # 渲染器（WebEngine / Sprite）
├── llm/                       # LLM 接口
│   ├── factory.py             # 工厂 + 配置
│   ├── provider.py            # 提供商实现
│   └── model_updater.py       # 模型列表更新
├── static/                    # 前端静态资源
│   ├── renderer.html          # 统一渲染页面
│   └── sdk/                   # Three.js / PixiJS / Live2D SDK
├── characters/                # 角色数据
│   ├── 初音未来/               # VRM 模型角色
│   ├── 永雏塔菲/
│   └── 胡桃/
├── frontend/                  # Vue 3 前端（开发中）
└── 技术方案/                   # 设计文档
```

## 🔧 核心工作流

### 对话流程
```
用户输入
  ↓
组装 System Prompt = 角色人格 + 环境感知 + 记忆召回 + 音乐画像
  ↓
调用 LLM Provider.chat()
  ↓
异步存储对话到记忆系统
  ↓
返回回复
```

### 记忆检索评分
```
综合得分 = 向量相似度 × 0.5
         + 时间衰减  × 0.2
         + 重要性    × 0.2
         + 关键词    × 0.1
```

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Windows 10/11（媒体感知依赖 Win32 API）

### 安装

```bash
# 克隆仓库
git clone git@github.com:rainwind0408/desktop-pet.git
cd desktop-pet

# 安装依赖
pip install -r requirements.txt
```

### 配置 LLM

编辑 `llm/llm_config.json` 或在启动后通过 GUI 设置界面配置：

```json
{
  "provider": "deepseek",
  "model": "deepseek-v4-flash",
  "api_key": "sk-your-api-key-here"
}
```

或通过 API：
```bash
curl -X PUT http://127.0.0.1:5000/api/config/llm \
  -H "Content-Type: application/json" \
  -d '{"provider":"deepseek","model":"deepseek-v4-flash","api_key":"sk-xxx"}'
```

支持 12 家 LLM 提供商：OpenAI、DeepSeek、通义千问、智谱、月之暗面、Anthropic、百度文心、MiniMax、阶跃星辰、豆包、Ollama（本地）、自定义兼容。

### 运行

```bash
python main.py
```

启动后：
- 桌面宠物窗口自动出现（无边框、透明背景、置顶）
- Flask API 运行在 `http://127.0.0.1:5000`
- 左键拖拽移动，右键菜单操作
- 系统托盘常驻

---

## 📡 API 端点

### 角色管理
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/characters` | 角色列表 |
| GET | `/api/character/current` | 当前角色 |
| POST | `/api/character/switch` | 切换角色 |
| POST | `/api/character/create` | 创建角色 |
| DELETE | `/api/character/<id>` | 删除角色 |
| POST | `/api/character/chat` | AI 对话 |

### 环境 / 记忆 / 交互
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/environment` | 环境上下文 |
| POST | `/api/environment/weather/refresh` | 刷新天气 |
| GET | `/api/memory/stats` | 记忆统计 |
| POST | `/api/memory/summary` | 生成摘要 |
| GET | `/api/interaction/decide` | 交互决策 |

### 配置
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config/llm` | LLM 配置 |
| PUT | `/api/config/llm` | 更新配置（热重载） |

---

## 🎭 角色数据格式

每个角色存放在 `characters/{角色名}/` 目录下：

```
characters/{角色名}/
├── profile.json           # 角色档案（必需）
├── memory_metadata.db     # 记忆数据库（自动）
├── memory_index.faiss     # 向量索引（自动）
├── music_history.db       # 播放历史（自动）
├── music_profile.json     # 音乐画像（自动）
├── 记忆摘要.txt            # 可读摘要（自动）
└── assets/
    ├── index.html         # 渲染页面（必需）
    └── model/
        ├── character.vrm  # 模型文件
        └── textures/      # 纹理
```

### profile.json 示例

```json
{
  "characterId": "hatsune_miku",
  "name": "初音未来",
  "appearance": {
    "modelPath": "assets/model/miku.vrm",
    "styleType": "vrm"
  },
  "personality": {
    "prompt": "你是初音未来...",
    "tone": "cheerful",
    "style": "energetic"
  }
}
```

---

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| 桌面窗口 | PyQt5（无边框、透明、置顶、拖拽、托盘） |
| 后端服务 | Flask REST API（22 个端点） |
| 向量检索 | FAISS（自动从 FlatIP 升级到 IVFFlat） |
| 数据存储 | SQLite（WAL 模式 + 连接池） |
| 加密 | Fernet AES-128-CBC（敏感信息自动加密） |
| LLM 接口 | 12 家提供商统一接口（OpenAI 兼容 + Anthropic） |
| 3D 渲染 | Three.js 0.146.0 + three-vrm 1.0.6 |
| 2D 渲染 | PixiJS 6.5.10 + pixi-live2d-display 0.4.0 |
| Web 前端 | Vue 3 + Vite（开发中） |

---

## 📋 已知限制

- **仅 Windows 平台**：媒体感知依赖 Win32 API 和 SMTC
- **模型文件需自行准备**：角色目录只包含配置，VRM/Live2D 模型文件需自行添加
- **网络依赖**：天气获取需要网络，无网络时使用缓存数据
- **Embedding 降级**：无 API Key 时使用 n-gram 哈希，检索精度降低

---

## 📄 许可证

MIT License
