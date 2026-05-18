"""
交互决策模块
负责情境分析、主动交互决策、防打扰机制
"""

import json
import os
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional


class InteractionDecider:
    """交互决策器：基于环境感知和媒体状态决定桌宠行为"""

    # 高优先级情境（无视冷却时间）
    HIGH_PRIORITY_TRIGGERS = {
        "birthday_detected", "user_long_idle", "sad_music_detected",
        "emergency_keyword", "first_meet_today",
    }

    # 情境-反应规则表
    SITUATION_RULES = [
        # (条件函数, 反应描述, 优先级, 动画标签)
        # 优先级: 3=高(无视冷却), 2=中(正常), 1=低(仅空闲时)
    ]

    def __init__(
        self,
        llm_call: Optional[Callable] = None,
        environment_sensor=None,
        cooldown_seconds: int = 600,
        summary_interval: int = 420,
        idle_threshold: int = 1800,
    ):
        self.llm_call = llm_call
        self.environment_sensor = environment_sensor
        self.cooldown_seconds = cooldown_seconds
        self.summary_interval = summary_interval
        self.idle_threshold = idle_threshold

        self._last_interaction_time: float = 0
        self._last_summary_time: float = 0
        self._behavior_log: List[Dict] = []
        self._behavior_lock = threading.Lock()
        self._running = False
        self._summary_thread: Optional[threading.Thread] = None

        # 当前媒体状态（由外部更新）
        self.media_state: Dict = {
            "music_playing": False,
            "music_title": "",
            "music_bpm": 0,
            "music_genre": "",
            "video_playing": False,
            "video_title": "",
            "video_tags": [],
            "active_window_title": "",
        }

        # 用户空闲追踪
        self._last_input_time: float = time.time()
        self._idle_warned: bool = False

    def start(self):
        """启动后台行为总结线程"""
        if self._running:
            return
        self._running = True
        self._summary_thread = threading.Thread(
            target=self._summary_loop, daemon=True
        )
        self._summary_thread.start()

    def stop(self):
        """停止后台线程"""
        self._running = False

    def update_media_state(self, state: Dict):
        """更新媒体状态（由 media_sensor 调用）"""
        self.media_state.update(state)
        self._log_behavior("media_update", state)

    def notify_user_input(self):
        """通知用户有输入活动（键盘/鼠标）"""
        self._last_input_time = time.time()
        if self._idle_warned:
            self._idle_warned = False

    def decide(self) -> Optional[Dict]:
        """
        核心决策：返回交互建议或 None
        返回格式: {"type": str, "message": str, "animation": str, "priority": int}
        """
        now = time.time()

        # 收集当前情境
        situation = self._analyze_situation()

        # 规则驱动决策（高优先级可突破冷却）
        rule_result = self._rule_based_decide(situation)
        if rule_result and rule_result["priority"] >= 3:
            self._last_interaction_time = now
            return rule_result

        # 冷却中则不交互
        if now - self._last_interaction_time < self.cooldown_seconds:
            return None

        if rule_result:
            self._last_interaction_time = now
            return rule_result

        return None

    def _analyze_situation(self) -> Dict:
        """分析当前情境，汇总所有感知数据"""
        now = datetime.now()
        hour = now.hour

        situation = {
            "hour": hour,
            "is_late_night": hour >= 23 or hour < 6,
            "is_morning": 6 <= hour < 9,
            "media": dict(self.media_state),
            "user_idle_seconds": time.time() - self._last_input_time,
            "is_user_idle": (time.time() - self._last_input_time) > self.idle_threshold,
        }

        # 环境感知数据
        if self.environment_sensor:
            try:
                time_info = self.environment_sensor.get_time_info()
                situation["time_info"] = time_info
            except Exception:
                pass

        return situation

    def _rule_based_decide(self, situation: Dict) -> Optional[Dict]:
        """规则驱动决策"""
        media = situation.get("media", {})
        hour = situation.get("hour", 12)

        # 高优先级：用户长时间未操作
        if situation.get("is_user_idle") and not self._idle_warned:
            self._idle_warned = True
            return {
                "type": "proactive_greeting",
                "message": "主人，你已经很久没理我了，休息一下吧~",
                "animation": "wave",
                "priority": 3,
            }

        # 深夜安静陪伴
        if situation.get("is_late_night"):
            if media.get("music_playing"):
                return {
                    "type": "late_night_companion",
                    "message": "夜深了，主人还在听歌呢...我陪你一起安静地听。",
                    "animation": "sit_quietly",
                    "priority": 2,
                }
            return {
                "type": "late_night_reminder",
                "message": "主人，已经很晚了，早点休息哦~",
                "animation": "sleepy",
                "priority": 2,
            }

        # 音乐节奏响应
        if media.get("music_playing"):
            bpm = media.get("music_bpm", 0)
            if bpm > 120:
                return {
                    "type": "music_fast",
                    "message": "这首歌节奏好快！",
                    "animation": "nod_fast",
                    "priority": 1,
                }
            elif 80 <= bpm <= 120:
                return {
                    "type": "music_medium",
                    "message": "好听~",
                    "animation": "nod_gentle",
                    "priority": 1,
                }

        # 恐怖视频检测
        if media.get("video_playing"):
            tags = media.get("video_tags", [])
            title = media.get("video_title", "")
            horror_keywords = ["恐怖", "惊悚", "horror", "scary", "鬼"]
            if any(kw in tags or kw in title for kw in horror_keywords):
                return {
                    "type": "horror_detected",
                    "message": "呜...主人你在看什么，好可怕！",
                    "animation": "scared",
                    "priority": 2,
                }

        # 早晨问候
        if situation.get("is_morning"):
            return {
                "type": "morning_greeting",
                "message": "早上好呀，主人！新的一天开始啦~",
                "animation": "wave",
                "priority": 1,
            }

        return None

    def generate_behavior_summary(self) -> Optional[str]:
        """调用 LLM 生成行为总结和互动建议"""
        if not self.llm_call:
            return None

        with self._behavior_lock:
            recent = list(self._behavior_log[-50:])
            self._behavior_log.clear()

        if not recent:
            return None

        # 构造总结提示
        behavior_desc = self._format_behavior_log(recent)
        prompt = f"""你是一个桌宠的行为分析助手。根据用户最近的行为记录，给出简短的互动建议。

用户最近的行为记录：
{behavior_desc}

请用 JSON 格式回复：
{{"summary": "行为总结（一句话）", "suggestion": "互动建议（适合桌宠说的一句话，不超过30字）", "mood": "用户可能的情绪（happy/neutral/tired/sad/excited）"}}

只返回 JSON，不要其他内容。"""

        try:
            response = self.llm_call([{"role": "user", "content": prompt}])
            # 尝试解析 JSON
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(response)
            self._log_behavior("llm_summary", result)
            return result.get("suggestion")
        except Exception as e:
            print(f"行为总结生成失败: {e}")
            return None

    def _format_behavior_log(self, logs: List[Dict]) -> str:
        """格式化行为日志为可读文本"""
        lines = []
        for entry in logs[-20:]:
            ts = entry.get("time", "")
            action = entry.get("action", "")
            data = entry.get("data", {})

            if action == "media_update":
                if data.get("music_playing"):
                    lines.append(f"[{ts}] 正在听歌: {data.get('music_title', '未知')}")
                if data.get("video_playing"):
                    lines.append(f"[{ts}] 正在看视频: {data.get('video_title', '未知')}")
                if data.get("active_window_title"):
                    lines.append(f"[{ts}] 活动窗口: {data.get('active_window_title')}")
            elif action == "llm_summary":
                lines.append(f"[{ts}] 行为总结: {data.get('summary', '')}")
        return "\n".join(lines) if lines else "暂无行为记录"

    def _log_behavior(self, action: str, data: Dict):
        """记录行为日志"""
        with self._behavior_lock:
            self._behavior_log.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": action,
                "data": data,
            })
            # 保留最近 200 条
            if len(self._behavior_log) > 200:
                self._behavior_log = self._behavior_log[-200:]

    def _summary_loop(self):
        """后台行为总结循环"""
        while self._running:
            time.sleep(60)  # 每分钟检查一次
            if not self._running:
                break

            now = time.time()
            if now - self._last_summary_time >= self.summary_interval:
                suggestion = self.generate_behavior_summary()
                if suggestion:
                    self._last_summary_time = now
                    # 存储建议供主循环读取
                    self._pending_suggestion = {
                        "type": "llm_suggestion",
                        "message": suggestion,
                        "animation": "think",
                        "priority": 1,
                    }

    def pop_pending_suggestion(self) -> Optional[Dict]:
        """取出待展示的 LLM 建议（非阻塞）"""
        suggestion = getattr(self, "_pending_suggestion", None)
        self._pending_suggestion = None
        return suggestion

    def get_status(self) -> Dict:
        """获取决策器状态"""
        return {
            "running": self._running,
            "cooldown_seconds": self.cooldown_seconds,
            "last_interaction": self._last_interaction_time,
            "behavior_log_count": len(self._behavior_log),
            "media_state": dict(self.media_state),
            "user_idle_seconds": round(time.time() - self._last_input_time),
        }
