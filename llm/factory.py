"""
LLM 工厂和配置管理
提供创建 LLM 提供者实例和管理配置文件的功能
"""

import json
import os
from typing import Dict, List, Optional

from .provider import BaseLLMProvider, OpenAICompatibleProvider, AnthropicProvider


# 配置文件目录
CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")

# 主配置文件路径（只存储当前激活的提供商）
MAIN_CONFIG_PATH = "llm/llm_config.json"


PROVIDER_PRESETS = {
    "openai": {
        "name": "OpenAI",
        "models": ["gpt-5.5", "gpt-5.5-instant", "gpt-5.5-pro", "gpt-4.1", "o4-mini"],
        "default_model": "gpt-4.1",
        "api_base": "https://api.openai.com/v1",
        "requires_api_key": True,
        "api_key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "name": "DeepSeek",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
        "default_model": "deepseek-v4-flash",
        "api_base": "https://api.deepseek.com/v1",
        "requires_api_key": True,
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "name": "通义千问 (Qwen)",
        "models": ["qwen3-max", "qwen3-plus", "qwen3-flash", "qwen3-omni-flash", "qwq-plus"],
        "default_model": "qwen3-flash",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "requires_api_key": True,
        "api_key_env": "QWEN_API_KEY",
    },
    "zhipu": {
        "name": "智谱 (GLM)",
        "models": ["glm-5", "glm-5-flash", "glm-5-turbo"],
        "default_model": "glm-5-flash",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "requires_api_key": True,
        "api_key_env": "ZHIPU_API_KEY",
    },
    "moonshot": {
        "name": "月之暗面 (Kimi)",
        "models": ["kimi-k2.6", "kimi-k2.5"],
        "default_model": "kimi-k2.6",
        "api_base": "https://api.moonshot.cn/v1",
        "requires_api_key": True,
        "api_key_env": "MOONSHOT_API_KEY",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "models": ["claude-sonnet-4-20250514", "claude-haiku-3-5-20250514"],
        "default_model": "claude-sonnet-4-20250514",
        "api_base": "https://api.anthropic.com",
        "requires_api_key": True,
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "baidu": {
        "name": "百度文心 (ERNIE)",
        "models": ["ernie-5.5", "ernie-5.5-turbo", "ernie-5.5-flash"],
        "default_model": "ernie-5.5-turbo",
        "api_base": "https://qianfan.baidubce.com/v2",
        "requires_api_key": True,
        "api_key_env": "BAIDU_API_KEY",
    },
    "minimax": {
        "name": "MiniMax",
        "models": ["MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5"],
        "default_model": "MiniMax-M2.7",
        "api_base": "https://api.minimaxi.com/v1",
        "requires_api_key": True,
        "api_key_env": "MINIMAX_API_KEY",
    },
    "stepfun": {
        "name": "阶跃星辰 (StepFun)",
        "models": ["step-3.5-flash", "step-3.5-pro", "step-3.5-mini"],
        "default_model": "step-3.5-flash",
        "api_base": "https://api.stepfun.com/v1",
        "requires_api_key": True,
        "api_key_env": "STEPFUN_API_KEY",
    },
    "doubao": {
        "name": "豆包 (ByteDance)",
        "models": ["doubao-seed-2.0-pro-256k", "doubao-seed-2.0-lite-128k", "doubao-seed-2.0-flash-256k", "doubao-seed-2.0-code"],
        "default_model": "doubao-seed-2.0-lite-128k",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "requires_api_key": True,
        "api_key_env": "DOUBAO_API_KEY",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "models": ["llama3", "qwen2.5", "mistral", "gemma2"],
        "default_model": "llama3",
        "api_base": "http://localhost:11434/v1",
        "requires_api_key": False,
        "api_key_env": "",
    },
    "custom": {
        "name": "自定义 OpenAI 兼容",
        "models": [],
        "default_model": "",
        "api_base": "",
        "requires_api_key": True,
        "api_key_env": "CUSTOM_API_KEY",
    },
}


def get_provider_config_path(provider_key: str) -> str:
    """获取提供商配置文件路径"""
    return os.path.join(CONFIG_DIR, f"{provider_key}.json")


def load_provider_config(provider_key: str) -> Dict:
    """加载指定提供商的配置文件"""
    config_path = get_provider_config_path(provider_key)
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_provider_config(provider_key: str, config: Dict) -> bool:
    """保存提供商配置到独立文件"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    config_path = get_provider_config_path(provider_key)
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


def load_main_config() -> Dict:
    """加载主配置文件（只存储当前激活的提供商）"""
    if os.path.exists(MAIN_CONFIG_PATH):
        try:
            with open(MAIN_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"provider": "deepseek"}


def save_main_config(config: Dict) -> bool:
    """保存主配置文件"""
    try:
        with open(MAIN_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


def get_full_config(provider_key: Optional[str] = None) -> Dict:
    """获取完整的配置（合并预设和用户配置）"""
    if not provider_key:
        main_config = load_main_config()
        provider_key = main_config.get("provider", "deepseek")

    preset = PROVIDER_PRESETS.get(provider_key, PROVIDER_PRESETS.get("custom", {}))
    user_config = load_provider_config(provider_key)

    # 合并配置，用户配置优先
    full_config = {
        "provider": provider_key,
        "model": user_config.get("model", preset.get("default_model", "")),
        "api_key": user_config.get("api_key", ""),
        "api_base": user_config.get("api_base", preset.get("api_base", "")),
        "temperature": user_config.get("temperature", 0.7),
        "max_tokens": user_config.get("max_tokens", 2000),
    }

    # 如果没有 api_key，尝试从环境变量获取
    if not full_config["api_key"] and preset.get("requires_api_key"):
        env_key = preset.get("api_key_env", "")
        if env_key:
            full_config["api_key"] = os.environ.get(env_key, "")

    return full_config


class LLMFactory:
    """LLM 工厂，根据配置创建对应的提供者实例"""

    @staticmethod
    def create(config: Dict) -> BaseLLMProvider:
        provider_key = config.get("provider", "openai")
        model = config.get("model", "")
        api_key = config.get("api_key", "")
        api_base = config.get("api_base", "")
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 2000)

        preset = PROVIDER_PRESETS.get(provider_key, PROVIDER_PRESETS.get("custom", {}))

        if not model:
            model = preset.get("default_model", "")

        if not api_base:
            api_base = preset.get("api_base", "")

        if not api_key and preset.get("requires_api_key"):
            env_key = preset.get("api_key_env", "")
            if env_key:
                api_key = os.environ.get(env_key, "")

        if provider_key == "anthropic":
            return AnthropicProvider(
                api_key=api_key,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        return OpenAICompatibleProvider(
            api_key=api_key,
            api_base=api_base,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            provider_name=provider_key,
        )

    @staticmethod
    def get_provider_list() -> List[Dict]:
        result = []
        for key, preset in PROVIDER_PRESETS.items():
            if key == "custom":
                continue
            result.append({
                "key": key,
                "name": preset["name"],
                "models": preset["models"],
                "default_model": preset["default_model"],
                "requires_api_key": preset["requires_api_key"],
            })
        result.append({
            "key": "custom",
            "name": PROVIDER_PRESETS["custom"]["name"],
            "models": [],
            "default_model": "",
            "requires_api_key": True,
        })
        return result
