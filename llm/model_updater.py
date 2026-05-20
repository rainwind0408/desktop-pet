"""
模型自动更新模块
负责定期拉取各厂商最新模型列表，实现自动同步更新
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
import requests

# 配置文件路径
CACHE_PATH = os.path.join(os.path.dirname(__file__), "model_cache.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "update_log.json")
UPDATE_INTERVAL_HOURS = 720  # 30 天

# 不支持标准 /v1/models 接口的提供商（已知）
UNSUPPORTED_PROVIDERS = {
    "baidu": "千帆 API 不提供标准 /v1/models 端点",
}

# 日志最大保留条数
MAX_LOG_RECORDS = 50


def get_cache_path() -> str:
    """获取缓存文件路径"""
    return CACHE_PATH


def load_cache() -> Dict:
    """加载模型缓存文件"""
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_cache(cache: Dict) -> bool:
    """保存模型缓存文件"""
    try:
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except IOError:
        return False


def is_update_needed(cache: Optional[Dict] = None) -> bool:
    """检查是否需要更新（超过30天）"""
    if cache is None:
        cache = load_cache()
    
    if not cache:
        return True
    
    last_update = cache.get("last_update", "")
    if not last_update:
        return True
    
    try:
        last_time = datetime.fromisoformat(last_update.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        hours_since_update = (now - last_time).total_seconds() / 3600
        return hours_since_update >= UPDATE_INTERVAL_HOURS
    except ValueError:
        return True


def fetch_models(provider_key: str, api_base: str, api_key: str = "") -> Optional[List[str]]:
    """
    从厂商 API 获取模型列表
    
    :param provider_key: 提供商标识
    :param api_base: API 基础 URL
    :param api_key: API 密钥（可选）
    :return: 模型名称列表，None 表示该厂商不支持标准接口
    """
    # 预判：已知不支持标准接口的厂商直接跳过
    if provider_key in UNSUPPORTED_PROVIDERS:
        print(f"跳过 {provider_key}: {UNSUPPORTED_PROVIDERS[provider_key]}")
        return None

    models = []
    
    try:
        headers = {}
        
        # 根据提供商设置不同的认证方式
        if provider_key == "anthropic":
            # Claude 使用 x-api-key 而非 Bearer
            if api_key:
                headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
            url = f"{api_base}/v1/models"
        elif provider_key == "ollama":
            # Ollama 本地接口，无需认证
            url = f"{api_base}/api/tags"
        else:
            # OpenAI 兼容接口
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            url = f"{api_base}/v1/models"
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # 不同厂商返回格式不同
            if provider_key == "ollama":
                # Ollama 返回格式: {"models": [{"name": "model:tag", ...}]}
                for model in data.get("models", []):
                    name = model.get("name", "")
                    if name:
                        models.append(name.split(':')[0])  # 只取模型名，去掉 tag
            elif provider_key == "anthropic":
                # Claude 返回格式: {"data": [{"name": "...", ...}]}
                for model in data.get("data", []):
                    name = model.get("name", "")
                    if name:
                        models.append(name)
            else:
                # OpenAI 兼容格式: {"data": [{"id": "...", ...}]}
                for model in data.get("data", []):
                    model_id = model.get("id", "")
                    if model_id:
                        models.append(model_id)
            
            # 去重并排序
            models = sorted(list(set(models)))
    
    except Exception as e:
        print(f"获取 {provider_key} 模型列表失败: {e}")
    
    return models


def compare_models(old_list: List[str], new_list: List[str]) -> Tuple[List[str], List[str]]:
    """
    对比新旧模型列表
    
    :param old_list: 旧模型列表
    :param new_list: 新模型列表
    :return: (新增模型, 移除模型)
    """
    old_set = set(old_list)
    new_set = set(new_list)
    
    added = sorted(list(new_set - old_set))
    removed = sorted(list(old_set - new_set))
    
    return added, removed


def sync_provider(provider_key: str, api_base: str, api_key: str = "", 
                  default_model: str = "") -> Optional[Dict]:
    """
    同步单个提供商的模型列表
    
    :param provider_key: 提供商标识
    :param api_base: API 基础 URL
    :param api_key: API 密钥
    :param default_model: 默认模型
    :return: 同步后的提供商配置，None 表示该厂商不支持接口直接跳过
    """
    # 获取当前缓存中的模型列表
    cache = load_cache()
    providers = cache.get("providers", {})
    existing = providers.get(provider_key, {})
    old_models = existing.get("models", [])

    # 拉取新模型列表
    new_models = fetch_models(provider_key, api_base, api_key)

    # fetch_models 返回 None 表示厂商不支持标准接口
    if new_models is None:
        print(f"  {provider_key}: 不支持标准接口，标记为仅手动更新")
        result = {
            "models": old_models if old_models else [],
            "default_model": default_model or existing.get("default_model", ""),
            "api_base": api_base,
            "fetched_at": existing.get("fetched_at", ""),
            "fetch_status": "manual",
            "unsupported_reason": UNSUPPORTED_PROVIDERS.get(provider_key, "")
        }
        return result

    # 如果拉取失败（空列表且无缓存），使用旧列表或默认值
    if not new_models:
        if old_models:
            print(f"  拉取 {provider_key} 失败，保留旧模型列表")
            result = dict(existing)
            result["fetch_status"] = "failed"
            return result
        else:
            print(f"  拉取 {provider_key} 失败且无缓存，使用空列表")
            return {
                "models": [],
                "default_model": default_model,
                "api_base": api_base,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "fetch_status": "failed"
            }

    # 对比差异
    added, removed = compare_models(old_models, new_models)

    if added or removed:
        print(f"  [{provider_key}] 模型变更: +{len(added)} 新增, -{len(removed)} 移除")
        if added:
            print(f"    新增: {', '.join(added)}")
        if removed:
            print(f"    移除: {', '.join(removed)}")

    return {
        "models": new_models,
        "default_model": default_model if default_model else existing.get("default_model", ""),
        "api_base": api_base,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "success",
        "added": added or [],
        "removed": removed or []
    }


def sync_all_providers(provider_presets: Dict, provider_configs: Dict) -> bool:
    """
    同步所有提供商的模型列表
    
    :param provider_presets: 预设配置（包含 api_base, default_model）
    :param provider_configs: 用户配置（包含 api_key）
    :return: 是否同步成功
    """
    print("\n[模型更新] 开始同步提供商模型列表...")

    cache = load_cache()
    providers = cache.get("providers", {})

    # 收集结果用于日志和内存刷新
    results = {
        "success": {},
        "skipped": {},
        "failed": {}
    }

    for key, preset in provider_presets.items():
        if key == "custom":
            # 自定义提供商跳过，由用户自行管理
            results["skipped"][key] = "自定义提供商"
            continue

        api_base = preset.get("api_base", "")
        default_model = preset.get("default_model", "")
        user_config = provider_configs.get(key, {})
        api_key = user_config.get("api_key", "")

        # 无 API Key 且不在 UNSUPPORTED_PROVIDERS 中的厂商，跳过
        if not api_key and key not in UNSUPPORTED_PROVIDERS:
            print(f"  ⏭️ {key} ({preset.get('name', key)}): 未配置 API Key，跳过")
            results["skipped"][key] = "未配置 API Key"
            continue

        print(f"  同步 {key} ({preset.get('name', key)})...")
        result = sync_provider(key, api_base, api_key, default_model)

        if result:
            providers[key] = result
            status = result.get("fetch_status", "unknown")
            if status == "manual":
                results["skipped"][key] = result.get("unsupported_reason", "不支持标准接口")
            elif status == "failed":
                results["failed"][key] = "API 调用失败"
            else:
                results["success"][key] = {
                    "added": result.get("added", []),
                    "removed": result.get("removed", [])
                }
        else:
            print(f"    ❌ 同步失败，保留旧配置")
            results["failed"][key] = "同步返回空"

    # 更新缓存
    cache["providers"] = providers
    cache["last_update"] = datetime.now(timezone.utc).isoformat()
    cache["update_interval_hours"] = UPDATE_INTERVAL_HOURS

    success = save_cache(cache)

    # v2: 同步完成后刷新内存并记录日志
    _refresh_after_sync(results)

    return success


def _refresh_after_sync(results: Dict):
    """同步完成后刷新内存中的模型列表，写入更新日志"""
    # 延迟导入避免循环依赖
    try:
        from .factory import reload_models
        reload_models()
        print("[模型更新] 内存模型列表已刷新")
    except ImportError:
        pass  # factory 未就绪时跳过

    # 写入更新日志
    _write_update_log(results)

    # 输出变更摘要
    _print_update_summary(results)


def _write_update_log(results: Dict):
    """将更新详情写入 update_log.json"""
    try:
        log_data = {"records": []}
        if os.path.exists(LOG_PATH):
            try:
                with open(LOG_PATH, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "auto_update",
            "summary": (
                f"同步完成: {len(results['success'])} 成功, "
                f"{len(results['skipped'])} 跳过, "
                f"{len(results['failed'])} 失败"
            ),
            "details": {
                "success": results["success"],
                "skipped": results["skipped"],
                "failed": results["failed"]
            }
        }

        records = log_data.get("records", [])
        records.insert(0, record)

        # 保留最近 N 条记录
        if len(records) > MAX_LOG_RECORDS:
            records = records[:MAX_LOG_RECORDS]

        log_data["records"] = records

        with open(LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[模型更新] 写入更新日志失败: {e}")


def _print_update_summary(results: Dict):
    """输出更新摘要到控制台"""
    total_success = len(results["success"])
    total_skipped = len(results["skipped"])
    total_failed = len(results["failed"])

    # 详细输出
    if results["success"]:
        for key, detail in results["success"].items():
            added = detail.get("added", [])
            removed = detail.get("removed", [])
            if added or removed:
                parts = []
                if added:
                    parts.append(f"+{len(added)} 新增 ({', '.join(added[:3])}{'...' if len(added) > 3 else ''})")
                if removed:
                    parts.append(f"-{len(removed)} 移除 ({', '.join(removed[:3])}{'...' if len(removed) > 3 else ''})")
                print(f"    ✅ {key}: {', '.join(parts)}")
            else:
                print(f"    ✅ {key}: 无变更")

    if results["skipped"]:
        for key, reason in results["skipped"].items():
            if isinstance(reason, dict):
                reason = reason.get("unsupported_reason", "跳过")
            print(f"    ⏭️ {key}: {reason}")

    if results["failed"]:
        for key, reason in results["failed"].items():
            print(f"    ❌ {key}: {reason}")

    print(f"\n[模型更新] 完成: {total_success} 成功, {total_skipped} 跳过, {total_failed} 失败")
    if total_success + total_failed > 0:
        print("[模型更新] 新模型列表下次打开设置时生效")


def start_background_updater(provider_presets: Dict, provider_configs: Dict, 
                             check_interval_hours: int = 24):
    """
    启动后台更新线程
    
    :param provider_presets: 预设配置
    :param provider_configs: 用户配置
    :param check_interval_hours: 检查间隔（小时）
    """
    def update_loop():
        while True:
            try:
                if is_update_needed():
                    sync_all_providers(provider_presets, provider_configs)
            except Exception as e:
                print(f"后台更新线程异常: {e}")
            
            # 等待指定时间后再次检查
            time.sleep(check_interval_hours * 3600)
    
    # 启动 daemon 线程
    thread = threading.Thread(target=update_loop, daemon=True)
    thread.start()
    print("模型自动更新线程已启动")


def initialize_cache(provider_presets: Dict):
    """
    初始化缓存（如果不存在）
    
    :param provider_presets: 预设配置
    """
    if os.path.exists(CACHE_PATH):
        return  # 缓存已存在
    
    print("初始化模型缓存...")
    
    cache = {
        "last_update": datetime.now(timezone.utc).isoformat(),
        "update_interval_hours": UPDATE_INTERVAL_HOURS,
        "providers": {}
    }
    
    for key, preset in provider_presets.items():
        cache["providers"][key] = {
            "models": preset.get("models", []),
            "default_model": preset.get("default_model", ""),
            "api_base": preset.get("api_base", ""),
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
    
    save_cache(cache)
    print("模型缓存初始化完成")


def get_models_for(provider_key: str) -> List[str]:
    """
    获取指定提供商的模型列表
    
    :param provider_key: 提供商标识
    :return: 模型名称列表
    """
    cache = load_cache()
    providers = cache.get("providers", {})
    provider = providers.get(provider_key, {})
    return provider.get("models", [])


def get_default_model(provider_key: str) -> str:
    """
    获取指定提供商的默认模型
    
    :param provider_key: 提供商标识
    :return: 默认模型名称
    """
    cache = load_cache()
    providers = cache.get("providers", {})
    provider = providers.get(provider_key, {})
    return provider.get("default_model", "")
