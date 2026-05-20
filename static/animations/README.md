# 动画文件目录

将动画文件放在此目录下，系统会自动加载。

## 支持格式

| 格式 | 说明 | 来源 |
|------|------|------|
| `.glb` | GLTF 二进制格式（推荐） | Blender 导出 / Mixamo 下载 |
| `.bvh` | 动作捕捉格式 | Mixamo / 动捕设备 |
| `.json` | 自定义 JSON 格式 | 手工制作或脚本导出 |

## 文件命名建议

```
static/animations/
  idle.glb        - 待机站立
  walk.glb        - 走路
  run.glb         - 跑步
  sit.glb         - 坐下
  wave.glb        - 挥手
  dance.glb       - 跳舞
  happy.glb       - 开心
  sad.glb         - 悲伤
  angry.glb       - 生气
```

## 在 profile.json 中配置

```json
{
  "appearance": {
    "styleType": "vrm",
    "modelPath": "assets/model/character.vrm",
    "animations": {
      "idle": "idle.glb",
      "walk": "walk.glb",
      "wave": "wave.glb",
      "sit": "sit.glb"
    }
  }
}
```

动画名称（如 "idle"）即为 playMotion 时传入的语义名。

## Mixamo 使用方法

1. 访问 https://www.mixamo.com
2. 登录 Adobe 账号
3. 选择任意角色预览动画
4. Download → Format: FBX → 勾选 Without Skin
5. 用 Blender 转换为 GLB（File → Export → glTF 2.0）
6. 将 .glb 文件放入此目录
