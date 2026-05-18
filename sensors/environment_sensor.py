"""
时空环境感知模块
负责采集时间、纪念日、天气数据，组装环境提示词
"""

import json
import os
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Optional


class EnvironmentSensor:
    def __init__(self, cache_file: str = "environment_cache.json"):
        self.cache_file = cache_file
        self.cache: Dict = {}
        self._load_cache()
        self._weather_fetching = False

    def _load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.cache = {}

    def _save_cache(self):
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def get_time_info(self) -> Dict:
        now = datetime.now()
        weekday_map = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

        hour = now.hour
        if 5 <= hour < 8:
            period = "清晨"
        elif 8 <= hour < 12:
            period = "上午"
        elif 12 <= hour < 14:
            period = "中午"
        elif 14 <= hour < 18:
            period = "下午"
        elif 18 <= hour < 22:
            period = "傍晚"
        else:
            period = "深夜"

        month = now.month
        if 3 <= month <= 5:
            season = "春天"
        elif 6 <= month <= 8:
            season = "夏天"
        elif 9 <= month <= 11:
            season = "秋天"
        else:
            season = "冬天"

        return {
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y年%m月%d日"),
            "weekday": weekday_map[now.weekday()],
            "hour": hour,
            "period": period,
            "month": month,
            "season": season,
            "timestamp": now.timestamp()
        }

    def get_anniversary_info(self, first_met_timestamp: Optional[float] = None) -> Dict:
        if not first_met_timestamp:
            return {"days_known": 0, "is_special_day": False, "description": ""}

        first_met = datetime.fromtimestamp(first_met_timestamp)
        now = datetime.now()
        days = (now - first_met).days

        special_days = [1, 7, 30, 100, 200, 365, 500, 730, 1000]
        is_special = days in special_days

        description = ""
        if is_special:
            if days == 1:
                description = "今天是相识的第1天！"
            elif days == 100:
                description = "今天是相识的第100天纪念日！"
            elif days == 365:
                description = "今天是相识一周年纪念日！"
            else:
                description = f"今天是相识的第{days}天纪念日！"

        return {
            "days_known": days,
            "is_special_day": is_special,
            "description": description
        }

    def get_weather_info(self, city: str = "auto") -> Dict:
        cache_key = f"weather_{datetime.now().strftime('%Y%m%d_%H')}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 尝试从当天缓存获取（即使过期也比没有好）
        day_key = f"weather_{datetime.now().strftime('%Y%m%d')}"
        for k, v in self.cache.items():
            if k.startswith(day_key):
                return v

        # 异步获取天气，先返回默认值
        if not self._weather_fetching:
            threading.Thread(
                target=self._fetch_weather_async,
                args=(city, cache_key),
                daemon=True,
            ).start()

        return {
            "city": city if city != "auto" else "本地",
            "condition": "未知",
            "temperature": 20,
            "temp_min": 15,
            "temp_max": 25,
            "humidity": 50,
            "wind": "微风",
            "description": "天气数据获取中...",
        }

    def _fetch_weather_async(self, city: str, cache_key: str):
        self._weather_fetching = True
        try:
            weather = self._fetch_weather_wttr(city)
            if weather:
                self.cache[cache_key] = weather
                self._save_cache()
        except Exception as e:
            print(f"天气获取失败: {e}")
        finally:
            self._weather_fetching = False

    def _fetch_weather_wttr(self, city: str) -> Optional[Dict]:
        """通过 wttr.in 获取天气（免费，无需 API Key）"""
        try:
            location = city if city != "auto" else ""
            url = f"https://wttr.in/{location}?format=j1&lang=zh"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            current = data.get("current_condition", [{}])[0]
            area = data.get("nearest_area", [{}])[0]
            area_name = area.get("areaName", [{}])[0].get("value", "未知")

            # 提取天气描述
            weather_desc = current.get("lang_zh", [{}])
            if weather_desc:
                condition = weather_desc[0].get("value", current.get("weatherDesc", [{}])[0].get("value", ""))
            else:
                condition = current.get("weatherDesc", [{}])[0].get("value", "未知")

            temp_c = int(current.get("temp_C", 20))
            humidity = int(current.get("humidity", 50))
            windspeed = float(current.get("windspeedKmph", 10))

            # 风力描述
            if windspeed < 12:
                wind = "微风"
            elif windspeed < 30:
                wind = "轻风"
            elif windspeed < 50:
                wind = "中风"
            else:
                wind = "大风"

            return {
                "city": area_name,
                "condition": condition,
                "temperature": temp_c,
                "temp_min": temp_c - 3,
                "temp_max": temp_c + 3,
                "humidity": humidity,
                "wind": wind,
                "description": f"{area_name}，{condition}，{temp_c}℃，{wind}，湿度{humidity}%",
            }
        except Exception as e:
            print(f"wttr.in 请求失败: {e}")
            return None

    def get_mood_params(self, weather: Dict, anniversary: Dict) -> Dict:
        temp = weather.get("temperature", 20)
        condition = weather.get("condition", "")

        mood_tag = "neutral"
        excitement_level = 0.5

        if temp < 10:
            mood_tag = "concern_cold"
        elif temp > 35:
            mood_tag = "concern_hot"
        elif "雨" in condition:
            mood_tag = "gentle_rain"
        elif "雪" in condition:
            mood_tag = "cozy_snow"

        if anniversary.get("is_special_day"):
            excitement_level = 0.9

        return {
            "mood_tag": mood_tag,
            "excitement_level": excitement_level
        }

    def build_environment_prompt(
        self,
        first_met_timestamp: Optional[float] = None,
        city: str = "auto"
    ) -> str:
        time_info = self.get_time_info()
        weather = self.get_weather_info(city)
        anniversary = self.get_anniversary_info(first_met_timestamp)
        mood = self.get_mood_params(weather, anniversary)

        mood_guidance = {
            "concern_cold": "外面很冷，多用温暖、关心的语气，可以提醒主人加衣服。",
            "concern_hot": "天气炎热，语气体贴关心，提醒主人注意防暑降温。",
            "gentle_rain": "外面在下雨，语气温柔，可以提醒主人带伞。",
            "cozy_snow": "外面在下雪，语气温馨浪漫，适合聊温暖的话题。",
            "neutral": "保持自然亲切的语气。",
        }
        mood_text = mood_guidance.get(mood["mood_tag"], mood_guidance["neutral"])

        excitement = mood.get("excitement_level", 0.5)
        if excitement >= 0.8:
            excitement_text = "今天是特殊日子，语气体现出开心和期待，可以多用感叹号。"
        elif excitement >= 0.6:
            excitement_text = "心情不错，语气轻快活泼。"
        else:
            excitement_text = ""

        prompt = f"""[当前环境感知]
- 物理时间：{time_info['date']}，{time_info['weekday']}，{time_info['period']}（{time_info['season']}时节）。
- 天气状况：{weather.get('city', '')}，{weather.get('condition', '未知')}，当前气温 {weather.get('temperature', '?')}℃，{weather.get('wind', '微风')}，湿度{weather.get('humidity', '?')}%。
- 情感羁绊：相识第 {anniversary['days_known']} 天。{anniversary['description']}

[行为指导]
你是主人的专属伴侣。{mood_text}{excitement_text}
不要生硬地报出数据，要把这些信息融入到日常的关心或闲聊中。"""

        return prompt

    def get_environment_context(self, first_met_timestamp: Optional[float] = None) -> Dict:
        time_info = self.get_time_info()
        weather = self.get_weather_info()
        anniversary = self.get_anniversary_info(first_met_timestamp)
        mood = self.get_mood_params(weather, anniversary)

        return {
            "time": time_info,
            "weather": weather,
            "anniversary": anniversary,
            "mood": mood
        }