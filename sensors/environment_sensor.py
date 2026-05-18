"""
时空环境感知模块
负责采集时间、纪念日、天气数据，组装环境提示词

支持多个免费天气数据源：
1. wttr.in - 无需 API Key，全球可用
2. Open-Meteo - 无需 API Key，高精度
3. 备用缓存 - 网络失败时使用
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
    def __init__(self, cache_file: str = "sensors/environment_cache.json"):
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
        """获取天气信息，支持缓存和多数据源"""
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
        """异步获取天气，尝试多个数据源"""
        self._weather_fetching = True
        try:
            # 尝试数据源 1: wttr.in
            weather = self._fetch_weather_wttr(city)
            if weather:
                self.cache[cache_key] = weather
                self._save_cache()
                return

            # 尝试数据源 2: Open-Meteo (需要坐标)
            weather = self._fetch_weather_openmeteo(city)
            if weather:
                self.cache[cache_key] = weather
                self._save_cache()
                return

            # 所有数据源失败，使用备用缓存
            print("所有天气数据源获取失败，使用备用缓存")
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

            # 提取天气描述（中文）
            weather_desc = current.get("lang_zh", [{}])
            if weather_desc and weather_desc[0].get("value"):
                condition = weather_desc[0]["value"]
            else:
                # 尝试英文描述并翻译
                condition_en = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
                condition = self._translate_weather(condition_en)

            temp_c = int(current.get("temp_C", 20))
            humidity = int(current.get("humidity", 50))
            windspeed = float(current.get("windspeedKmph", 10))

            # 风力描述
            wind = self._get_wind_description(windspeed)

            return {
                "city": area_name,
                "condition": condition,
                "temperature": temp_c,
                "temp_min": temp_c - 3,
                "temp_max": temp_c + 3,
                "humidity": humidity,
                "wind": wind,
                "description": f"{area_name}，{condition}，{temp_c}℃，{wind}，湿度{humidity}%",
                "source": "wttr.in",
            }
        except Exception as e:
            print(f"wttr.in 请求失败: {e}")
            return None

    def _fetch_weather_openmeteo(self, city: str) -> Optional[Dict]:
        """通过 Open-Meteo 获取天气（免费，无需 API Key，高精度）"""
        try:
            # 首先获取城市坐标
            lat, lon, city_name = self._get_city_coordinates(city)
            if lat is None:
                return None

            # 获取当前天气
            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
                f"&daily=temperature_2m_max,temperature_2m_min"
                f"&timezone=auto&forecast_days=1"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "DesktopPet/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            current = data.get("current", {})
            daily = data.get("daily", {})

            temp_c = round(current.get("temperature_2m", 20))
            humidity = round(current.get("relative_humidity_2m", 50))
            weather_code = current.get("weather_code", 0)
            windspeed = current.get("wind_speed_10m", 10)

            condition = self._get_weather_description(weather_code)
            wind = self._get_wind_description(windspeed)

            temp_max = round(daily.get("temperature_2m_max", [temp_c + 3])[0])
            temp_min = round(daily.get("temperature_2m_min", [temp_c - 3])[0])

            return {
                "city": city_name,
                "condition": condition,
                "temperature": temp_c,
                "temp_min": temp_min,
                "temp_max": temp_max,
                "humidity": humidity,
                "wind": wind,
                "description": f"{city_name}，{condition}，{temp_c}℃，{wind}，湿度{humidity}%",
                "source": "open-meteo",
            }
        except Exception as e:
            print(f"Open-Meteo 请求失败: {e}")
            return None

    def _get_city_coordinates(self, city: str) -> tuple:
        """获取城市坐标（使用 Open-Meteo Geocoding API）"""
        try:
            if city == "auto":
                # 使用 IP 定位
                return self._get_ip_location()

            # 搜索城市
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=zh"
            req = urllib.request.Request(url, headers={"User-Agent": "DesktopPet/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = data.get("results", [])
            if results:
                result = results[0]
                return result["latitude"], result["longitude"], result.get("name", city)
        except Exception:
            pass
        return None, None, city

    def _get_ip_location(self) -> tuple:
        """通过 IP 获取大致位置"""
        try:
            # 使用免费的 IP 定位服务
            url = "http://ip-api.com/json/?lang=zh-CN"
            req = urllib.request.Request(url, headers={"User-Agent": "DesktopPet/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("status") == "success":
                lat = data.get("lat")
                lon = data.get("lon")
                city_name = data.get("city", "未知")
                return lat, lon, city_name
        except Exception:
            pass
        # 默认北京坐标
        return 39.9042, 116.4074, "北京"

    def _get_weather_description(self, code: int) -> str:
        """将 WMO 天气代码转换为中文描述"""
        weather_codes = {
            0: "晴朗",
            1: "大部晴朗",
            2: "局部多云",
            3: "多云",
            45: "雾",
            48: "雾凇",
            51: "小毛毛雨",
            53: "中毛毛雨",
            55: "大毛毛雨",
            56: "冻毛毛雨",
            57: "强冻毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            66: "小冻雨",
            67: "大冻雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            77: "雪粒",
            80: "小阵雨",
            81: "中阵雨",
            82: "大阵雨",
            85: "小阵雪",
            86: "大阵雪",
            95: "雷暴",
            96: "雷暴伴小冰雹",
            99: "雷暴伴大冰雹",
        }
        return weather_codes.get(code, "未知")

    def _translate_weather(self, english_desc: str) -> str:
        """将英文天气描述翻译为中文"""
        translations = {
            "Clear": "晴朗",
            "Sunny": "晴天",
            "Partly Cloudy": "局部多云",
            "Cloudy": "多云",
            "Overcast": "阴天",
            "Mist": "薄雾",
            "Fog": "雾",
            "Light Rain": "小雨",
            "Rain": "雨",
            "Heavy Rain": "大雨",
            "Light Snow": "小雪",
            "Snow": "雪",
            "Heavy Snow": "大雪",
            "Thunderstorm": "雷暴",
            "Drizzle": "毛毛雨",
            "Showers": "阵雨",
        }
        for en, zh in translations.items():
            if en.lower() in english_desc.lower():
                return zh
        return english_desc

    def _get_wind_description(self, speed_kmph: float) -> str:
        """根据风速返回中文描述"""
        if speed_kmph < 1:
            return "无风"
        elif speed_kmph < 12:
            return "微风"
        elif speed_kmph < 30:
            return "轻风"
        elif speed_kmph < 50:
            return "中风"
        elif speed_kmph < 75:
            return "大风"
        else:
            return "狂风"

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
