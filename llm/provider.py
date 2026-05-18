"""
LLM 提供者实现
支持 OpenAI 兼容接口和 Anthropic Claude
"""

import json
import urllib.request
from abc import ABC, abstractmethod
from typing import Dict, List


class BaseLLMProvider(ABC):
    """LLM 提供者抽象基类"""

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass


class OpenAICompatibleProvider(BaseLLMProvider):
    """通用 OpenAI 兼容接口

    覆盖: OpenAI / DeepSeek / Qwen / Zhipu / Moonshot / Baichuan /
          MiniMax / StepFun / ByteDance(豆包) / Ollama / 自定义
    """

    def __init__(self, api_key: str, api_base: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 2000,
                 provider_name: str = "openai"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._provider_name = provider_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else str(e)
            raise RuntimeError(f"LLM API 错误 ({e.code}): {error_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"LLM 连接失败: {e.reason}")


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude 独立实现（非 OpenAI 兼容格式）"""

    def __init__(self, api_key: str, model: str,
                 temperature: float = 0.7, max_tokens: int = 2000):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        temperature = kwargs.get("temperature", self.temperature)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        system_msg = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                user_messages.append(msg)

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        body = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_msg,
            "messages": user_messages,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["content"][0]["text"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else str(e)
            raise RuntimeError(f"LLM API 错误 ({e.code}): {error_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"LLM 连接失败: {e.reason}")
