"""
Flask API 服务模块
提供前后端通信接口
"""

import json
import os
from flask import Flask, request, jsonify
from flask_cors import CORS

from llm.factory import (
    load_main_config, save_main_config,
    load_provider_config, save_provider_config,
    get_full_config, LLMFactory, get_provider_config_path
)


class APIServer:
    def __init__(self, character_manager=None, environment_sensor=None, memory_system=None, interaction_decider=None, media_sensor=None):
        self.app = Flask(__name__)
        CORS(self.app)

        self.character_manager = character_manager
        self.environment_sensor = environment_sensor
        self.memory_system = memory_system
        self.interaction_decider = interaction_decider
        self.media_sensor = media_sensor
        self._on_character_switched = None

        self._register_routes()

    def _register_routes(self):
        app = self.app

        @app.route('/api/characters', methods=['GET'])
        def get_characters():
            if not self.character_manager:
                return jsonify({"error": "角色管理器未初始化"}), 500
            characters = self.character_manager.get_available_characters()
            result = []
            for char_id in characters:
                try:
                    profile = self.character_manager.load_character_profile(char_id)
                    result.append({
                        "id": char_id,
                        "name": profile.get("name", char_id),
                        "description": profile.get("description", "")
                    })
                except Exception:
                    result.append({"id": char_id, "name": char_id, "description": ""})
            return jsonify(result)

        @app.route('/api/character/current', methods=['GET'])
        def get_current_character():
            if not self.character_manager:
                return jsonify({"error": "角色管理器未初始化"}), 500
            char_id = self.character_manager.current_character_id
            if not char_id:
                return jsonify({"name": "未选择", "description": ""})
            try:
                profile = self.character_manager.load_character_profile(char_id)
                return jsonify(profile)
            except Exception as e:
                return jsonify({"error": str(e)}), 404

        @app.route('/api/character/switch', methods=['POST'])
        def switch_character():
            if not self.character_manager:
                return jsonify({"error": "角色管理器未初始化"}), 500
            data = request.get_json()
            character_id = data.get("characterId", "")
            if not character_id:
                return jsonify({"error": "缺少 characterId"}), 400
            try:
                profile = self.character_manager.switch_character(character_id)
                if self._on_character_switched:
                    try:
                        from PyQt5.QtCore import QTimer
                        QTimer.singleShot(0, self._on_character_switched)
                    except Exception:
                        pass
                return jsonify(profile)
            except Exception as e:
                return jsonify({"error": str(e)}), 404

        @app.route('/api/character/create', methods=['POST'])
        def create_character():
            if not self.character_manager:
                return jsonify({"error": "角色管理器未初始化"}), 500
            data = request.get_json()
            if not data:
                return jsonify({"error": "缺少请求数据"}), 400

            character_id = data.get("characterId", "").strip()
            name = data.get("name", "").strip()
            if not character_id or not name:
                return jsonify({"error": "characterId 和 name 为必填项"}), 400

            try:
                profile = self.character_manager.create_character(
                    character_id=character_id,
                    name=name,
                    description=data.get("description", ""),
                    personality_prompt=data.get("personalityPrompt", ""),
                    tone=data.get("tone", "soft"),
                    style=data.get("style", "polite"),
                    theme=data.get("theme", "pastel"),
                    model_path=data.get("modelPath", ""),
                )
                return jsonify(profile), 201
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/character/<character_id>', methods=['DELETE'])
        def delete_character(character_id):
            if not self.character_manager:
                return jsonify({"error": "角色管理器未初始化"}), 500
            try:
                self.character_manager.delete_character(character_id)
                return jsonify({"status": "ok", "message": f"角色 {character_id} 已删除"})
            except FileNotFoundError as e:
                return jsonify({"error": str(e)}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/character/save', methods=['POST'])
        def save_character():
            if not self.character_manager:
                return jsonify({"error": "角色管理器未初始化"}), 500
            data = request.get_json()
            character_id = data.get("characterId", "")
            if not character_id:
                return jsonify({"error": "缺少 characterId"}), 400
            try:
                self.character_manager.save_character_profile(character_id, data)
                return jsonify({"status": "ok"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/character/chat', methods=['POST'])
        def chat():
            if not self.character_manager:
                return jsonify({"error": "角色管理器未初始化"}), 500
            data = request.get_json()
            message = data.get("message", "")
            if not message:
                return jsonify({"error": "缺少 message"}), 400

            try:
                response = self.character_manager.chat_with_character(message)
                return jsonify({"response": response})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/environment', methods=['GET'])
        def get_environment():
            if not self.environment_sensor:
                return jsonify({"error": "环境感知模块未初始化"}), 500

            # 获取当前角色的初次相识时间
            first_met = None
            if self.character_manager and self.character_manager.current_character_id:
                try:
                    profile = self.character_manager.load_character_profile(
                        self.character_manager.current_character_id
                    )
                    first_met = profile.get("firstMetTimestamp")
                except Exception:
                    pass

            context = self.environment_sensor.get_environment_context(first_met)
            return jsonify(context)

        @app.route('/api/environment/weather/refresh', methods=['POST'])
        def refresh_weather():
            if not self.environment_sensor:
                return jsonify({"error": "环境感知模块未初始化"}), 500
            # 清除天气缓存并重新获取
            keys_to_remove = [k for k in self.environment_sensor.cache if k.startswith("weather_")]
            for k in keys_to_remove:
                del self.environment_sensor.cache[k]
            self.environment_sensor._save_cache()
            weather = self.environment_sensor.get_weather_info()
            return jsonify({"status": "ok", "weather": weather})

        @app.route('/api/memory/stats', methods=['GET'])
        def get_memory_stats():
            if not self.character_manager or not self.memory_system:
                return jsonify({"error": "记忆系统未初始化"}), 500
            char_id = self.character_manager.current_character_id
            if not char_id:
                return jsonify({"error": "未选择角色"}), 400
            stats = self.memory_system.get_memory_stats(char_id)
            return jsonify(stats)

        @app.route('/api/memory/<character_id>', methods=['DELETE'])
        def delete_character_memories(character_id):
            if not self.memory_system:
                return jsonify({"error": "记忆系统未初始化"}), 500
            try:
                self.memory_system.delete_character_memories(character_id)
                return jsonify({"status": "ok", "message": f"角色 {character_id} 的记忆已删除"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/memory/summary', methods=['POST'])
        def generate_memory_summary():
            if not self.character_manager or not self.memory_system:
                return jsonify({"error": "记忆系统未初始化"}), 500
            char_id = self.character_manager.current_character_id
            if not char_id:
                return jsonify({"error": "未选择角色"}), 400
            try:
                llm_call = None
                if hasattr(self.character_manager, 'llm_provider') and self.character_manager.llm_provider:
                    def llm_call(prompt):
                        return self.character_manager.llm_provider.chat([{"role": "user", "content": prompt}])
                summary = self.memory_system.generate_memory_summary(char_id, llm_call)
                return jsonify({"summary": summary})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/memory/rebuild', methods=['POST'])
        def rebuild_faiss_index():
            if not self.character_manager or not self.memory_system:
                return jsonify({"error": "记忆系统未初始化"}), 500
            char_id = self.character_manager.current_character_id
            if not char_id:
                return jsonify({"error": "未选择角色"}), 400
            try:
                self.memory_system._rebuild_faiss_index(char_id)
                return jsonify({"status": "ok", "message": "FAISS 索引已重建"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/config/llm/providers', methods=['GET'])
        def get_llm_providers():
            providers = LLMFactory.get_provider_list()
            return jsonify(providers)

        @app.route('/api/config/llm', methods=['GET'])
        def get_llm_config():
            try:
                main_config = load_main_config()
                current_provider = main_config.get("provider", "deepseek")
                full_config = get_full_config(current_provider)
                full_config["provider"] = current_provider
                # 隐藏 API Key
                full_config["api_key"] = "***" if full_config.get("api_key") else ""
                return jsonify(full_config)
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/config/llm/provider', methods=['GET'])
        def get_llm_provider_config():
            """获取指定提供商的配置"""
            provider_key = request.args.get("provider", "")
            if not provider_key:
                return jsonify({"error": "缺少 provider 参数"}), 400
            try:
                config = load_provider_config(provider_key)
                # 隐藏 API Key
                config["api_key"] = "***" if config.get("api_key") else ""
                return jsonify(config)
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/config/llm', methods=['PUT', 'POST'])
        def update_llm_config():
            try:
                data = request.get_json()
                if not data:
                    return jsonify({"error": "缺少配置数据"}), 400

                provider_key = data.get("provider", "deepseek")

                # 构建配置数据
                config_data = {
                    "model": data.get("model", ""),
                    "api_key": data.get("api_key", ""),
                    "api_base": data.get("api_base", ""),
                    "temperature": float(data.get("temperature", 0.7)),
                    "max_tokens": int(data.get("max_tokens", 2000)),
                }

                # 如果 API Key 是 ***，保留原有的
                if config_data["api_key"] == "***":
                    existing = load_provider_config(provider_key)
                    config_data["api_key"] = existing.get("api_key", "")

                # 保存到提供商独立配置文件
                save_provider_config(provider_key, config_data)

                # 更新主配置文件（只记录当前提供商）
                save_main_config({"provider": provider_key})

                # 重新初始化 LLM
                if self.character_manager:
                    full_config = get_full_config(provider_key)
                    full_config["provider"] = provider_key
                    if full_config.get("api_key"):
                        try:
                            provider = LLMFactory.create(full_config)
                            self.character_manager.set_llm_provider(provider)
                            if self.interaction_decider:
                                self.interaction_decider.llm_call = lambda msgs: provider.chat(msgs)
                        except Exception as e:
                            print(f"LLM 重新初始化失败: {e}")

                return jsonify({"status": "ok", "provider": provider_key, "model": config_data["model"]})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/health', methods=['GET'])
        def health():
            return jsonify({
                "status": "ok",
                "character_manager": self.character_manager is not None,
                "environment_sensor": self.environment_sensor is not None,
                "memory_system": self.memory_system is not None,
                "interaction_decider": self.interaction_decider is not None,
                "media_sensor": self.media_sensor is not None
            })

        @app.route('/api/interaction/decide', methods=['GET'])
        def get_interaction_decision():
            if not self.interaction_decider:
                return jsonify({"error": "交互决策模块未初始化"}), 500
            decision = self.interaction_decider.decide()
            if not decision:
                decision = self.interaction_decider.pop_pending_suggestion()
            return jsonify({"decision": decision})

        @app.route('/api/interaction/media', methods=['POST'])
        def update_media_state():
            if not self.interaction_decider:
                return jsonify({"error": "交互决策模块未初始化"}), 500
            data = request.get_json()
            if not data:
                return jsonify({"error": "缺少请求数据"}), 400
            self.interaction_decider.update_media_state(data)
            return jsonify({"status": "ok"})

        @app.route('/api/interaction/input', methods=['POST'])
        def notify_user_input():
            if not self.interaction_decider:
                return jsonify({"error": "交互决策模块未初始化"}), 500
            self.interaction_decider.notify_user_input()
            return jsonify({"status": "ok"})

        @app.route('/api/interaction/status', methods=['GET'])
        def get_interaction_status():
            if not self.interaction_decider:
                return jsonify({"error": "交互决策模块未初始化"}), 500
            return jsonify(self.interaction_decider.get_status())

        @app.route('/api/media/state', methods=['GET'])
        def get_media_state():
            if not self.media_sensor:
                return jsonify({"error": "媒体感知模块未初始化"}), 500
            return jsonify(self.media_sensor.get_state())

        @app.route('/api/media/summary', methods=['GET'])
        def get_media_summary():
            if not self.media_sensor:
                return jsonify({"error": "媒体感知模块未初始化"}), 500
            return jsonify({"summary": self.media_sensor.get_perception_summary()})

    def run(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
        self.app.run(host=host, port=port, debug=debug, use_reloader=False)
