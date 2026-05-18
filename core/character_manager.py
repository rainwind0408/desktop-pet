"""
角色管理器模块
负责角色档案加载、创建、切换、对话管理
"""

import json
import os
import re
import time
from typing import Dict, List, Optional


class CharacterManager:
    def __init__(self, characters_dir: str = "characters"):
        self.current_character_id: Optional[str] = None
        self.characters_dir = characters_dir
        self.memory_system = None
        self.environment_sensor = None

    def set_memory_system(self, memory_system):
        self.memory_system = memory_system

    def set_environment_sensor(self, environment_sensor):
        self.environment_sensor = environment_sensor

    def get_available_characters(self) -> List[str]:
        if not os.path.exists(self.characters_dir):
            return []
        return [
            d for d in os.listdir(self.characters_dir)
            if os.path.isdir(os.path.join(self.characters_dir, d))
            and os.path.exists(os.path.join(self.characters_dir, d, "profile.json"))
        ]

    def load_character_profile(self, character_id: str) -> Dict:
        profile_path = os.path.join(
            self.characters_dir, character_id, "profile.json"
        )
        if not os.path.exists(profile_path):
            raise FileNotFoundError(f"角色档案不存在: {profile_path}")
        with open(profile_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def create_character(self, character_id: str, name: str, description: str = "",
                         personality_prompt: str = "", tone: str = "soft",
                         style: str = "polite", theme: str = "pastel",
                         model_path: str = "") -> Dict:
        """创建新角色，返回角色档案"""
        # 校验 character_id
        if not re.match(r'^[a-zA-Z0-9_\u4e00-\u9fff]+$', character_id):
            raise ValueError("角色ID只能包含字母、数字、下划线和中文")

        char_dir = os.path.join(self.characters_dir, character_id)
        if os.path.exists(char_dir) and os.path.exists(os.path.join(char_dir, "profile.json")):
            raise ValueError(f"角色 '{character_id}' 已存在")

        # 创建目录结构
        os.makedirs(os.path.join(char_dir, "assets", "model"), exist_ok=True)

        # 生成默认人设
        if not personality_prompt:
            personality_prompt = f"你是{name}，{description or '一个可爱的虚拟宠物'}。说话风格：{tone}。"

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        profile = {
            "characterId": character_id,
            "name": name,
            "description": description,
            "firstMetTimestamp": time.time(),
            "appearance": {
                "modelPath": model_path or "/assets/model/model.model3.json",
                "styleType": "live2d",
            },
            "personality": {
                "prompt": personality_prompt,
                "tone": tone,
                "style": style,
            },
            "preferences": {
                "voice": "default_01",
                "theme": theme,
            },
            "createdTime": now,
            "lastModified": now,
        }

        profile_path = os.path.join(char_dir, "profile.json")
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)

        print(f"角色创建成功：{name} ({character_id})")
        return profile

    def delete_character(self, character_id: str) -> bool:
        """删除角色及其所有数据"""
        import shutil

        char_dir = os.path.join(self.characters_dir, character_id)
        if not os.path.exists(char_dir):
            raise FileNotFoundError(f"角色 '{character_id}' 不存在")

        # 如果是当前角色，先清除
        if self.current_character_id == character_id:
            self.current_character_id = None

        # 清除记忆系统数据
        if self.memory_system:
            self.memory_system.delete_character_memories(character_id)

        # 删除整个角色目录
        shutil.rmtree(char_dir)
        print(f"角色已删除：{character_id}")
        return True

    def switch_character(self, character_id: str) -> Dict:
        profile = self.load_character_profile(character_id)
        self.current_character_id = character_id
        print(f"成功切换至角色：{profile['name']}")
        return profile

    def set_llm_provider(self, llm_provider):
        self.llm_provider = llm_provider

    def chat_with_character(self, user_input: str) -> str:
        if not self.current_character_id:
            return "请先选择一个角色！"

        profile = self.load_character_profile(self.current_character_id)

        personality_prompt = profile.get("personality", {}).get("prompt", "")

        env_prompt = ""
        if self.environment_sensor:
            first_met = profile.get("firstMetTimestamp")
            env_prompt = self.environment_sensor.build_environment_prompt(first_met)

        memory_prompt = ""
        if self.memory_system:
            memory_prompt = self.memory_system.build_memory_prompt(
                self.current_character_id, user_input
            )

        system_content = personality_prompt
        if env_prompt:
            system_content += f"\n\n{env_prompt}"
        if memory_prompt:
            system_content += f"\n\n{memory_prompt}"

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_input},
        ]

        if hasattr(self, 'llm_provider') and self.llm_provider:
            try:
                response = self.llm_provider.chat(messages)
            except Exception as e:
                response = f"[LLM 调用失败] {profile['name']}: 唔...我好像走神了...\n（错误: {e}）"
        else:
            response = f"[未配置 LLM] 角色「{profile['name']}」收到消息：{user_input}\n请在设置中配置 API 以启用 AI 对话。"

        if self.memory_system:
            self.memory_system.add_memory_async(
                self.current_character_id,
                f"用户: {user_input}",
                role="user"
            )
            self.memory_system.add_memory_async(
                self.current_character_id,
                f"AI: {response}",
                role="assistant"
            )

        return response

    def save_character_profile(self, character_id: str, profile: Dict):
        profile_path = os.path.join(
            self.characters_dir, character_id, "profile.json"
        )
        os.makedirs(os.path.dirname(profile_path), exist_ok=True)
        profile["lastModified"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)