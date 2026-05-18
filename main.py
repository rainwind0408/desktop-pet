"""
桌面虚拟宠物 - 主程序入口
整合 PyQt5 窗口、Flask API、角色管理、记忆系统、环境感知
"""

import atexit
import json
import os
import sys
import threading
from PyQt5.QtWidgets import QApplication
from gui import PetWindow
from core import CharacterManager, MemorySystem, MusicAnalyzer
from sensors import EnvironmentSensor, MediaSensor, MusicTracker
from decision import InteractionDecider
from api import APIServer
from llm import LLMFactory
from llm.factory import load_main_config, get_full_config


def start_api_server(api_server: APIServer):
    api_server.run(host="127.0.0.1", port=5000, debug=False)


def main():
    character_manager = CharacterManager()

    # 加载配置：从 llm_config.json 获取当前提供商，再从 llm/config/{provider}.json 获取完整配置
    main_config = load_main_config()
    current_provider = main_config.get("provider", "deepseek")
    llm_config = get_full_config(current_provider)
    llm_config["provider"] = current_provider

    memory_system = MemorySystem(llm_config=llm_config)
    atexit.register(memory_system.cleanup)  # 程序退出时清理资源
    environment_sensor = EnvironmentSensor()
    interaction_decider = InteractionDecider(environment_sensor=environment_sensor)
    media_sensor = MediaSensor(poll_interval=3.0)

    # 初始化音乐追踪系统
    character_name = character_manager.get_current_character_name() or "default"
    music_tracker = MusicTracker(db_path=f"characters/{character_name}/music_history.db")
    music_analyzer = MusicAnalyzer(
        tracker=music_tracker,
        profile_path=f"characters/{character_name}/music_profile.json"
    )
    atexit.register(music_tracker.cleanup_old_records, keep_days=90)  # 定期清理旧记录

    character_manager.set_memory_system(memory_system)
    character_manager.set_environment_sensor(environment_sensor)
    character_manager.set_music_analyzer(music_analyzer)

    api_key = llm_config.get("api_key", "")
    if api_key:
        try:
            provider = LLMFactory.create(llm_config)
            character_manager.set_llm_provider(provider)
            interaction_decider.llm_call = lambda msgs: provider.chat(msgs)
            print(f"LLM 已初始化: {llm_config.get('provider', 'unknown')} / {llm_config.get('model', 'unknown')}")
        except Exception as e:
            print(f"LLM 初始化失败: {e}")
    else:
        print("LLM 未配置 API Key，将在设置中配置后启用")

    # 媒体感知回调：交互决策 + 音乐记录
    def on_media_state_changed(state):
        interaction_decider.update_media_state(state)
        # 记录音乐播放
        if state.get("music_playing") and state.get("music_title"):
            music_tracker.record_play(
                title=state["music_title"],
                artist=state.get("music_artist", ""),
                platform=state.get("music_platform", ""),
                source="smtc"
            )

    # 启动媒体感知 -> 交互决策联动
    media_sensor.start(callback=on_media_state_changed)
    interaction_decider.start()

    api_server = APIServer(
        character_manager=character_manager,
        environment_sensor=environment_sensor,
        memory_system=memory_system,
        interaction_decider=interaction_decider,
        media_sensor=media_sensor,
    )

    api_thread = threading.Thread(
        target=start_api_server,
        args=(api_server,),
        daemon=True
    )
    api_thread.start()
    print("Flask API 服务已启动: http://127.0.0.1:5000")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    window.set_character_manager(character_manager)

    print("桌面宠物系统启动完成")
    print(f"可用角色: {character_manager.get_available_characters()}")

    characters = character_manager.get_available_characters()
    if characters:
        character_manager.switch_character(characters[0])

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
