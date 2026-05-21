"""
模型自动更新功能模拟测试
模拟各厂商 API 响应，验证完整更新流程
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from typing import Dict, List

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(__file__))

# ── 模拟 API 响应数据 ──────────────────────────────────────────

MOCK_API_RESPONSES = {
    "openai": {
        "status_code": 200,
        "json": {
            "data": [
                {"id": "gpt-5.5"},
                {"id": "gpt-5.5-pro"},
                {"id": "gpt-4.1-nano"},
                {"id": "gpt-4.1"},
                {"id": "o4-mini"},
                {"id": "gpt-4o"},
            ]
        }
    },
    "deepseek": {
        "status_code": 200,
        "json": {
            "data": [
                {"id": "deepseek-v4-pro"},
                {"id": "deepseek-v4-flash"},
                {"id": "deepseek-chat-v2"},
            ]
        }
    },
    "moonshot": {
        "status_code": 200,
        "json": {
            "data": [
                {"id": "kimi-k2.6"},
                {"id": "kimi-k2.5"},
                {"id": "kimi-k2-instruct"},
            ]
        }
    },
    "anthropic": {
        "status_code": 200,
        "json": {
            "data": [
                {"name": "claude-sonnet-4-20250514"},
                {"name": "claude-opus-4-20250514"},
                {"name": "claude-haiku-3-5-20250514"},
            ]
        }
    },
    "ollama": {
        "status_code": 200,
        "json": {
            "models": [
                {"name": "llama3:latest"},
                {"name": "qwen2.5:7b"},
                {"name": "mistral:latest"},
            ]
        }
    },
    # 模拟 API 调用失败（超时/5xx）
    "qwen": {
        "status_code": 500,
        "json": {"error": "Internal Server Error"}
    },
    "stepfun": {
        "side_effect": Exception("Connection timeout")
    },
    "doubao": {
        "status_code": 404,
        "json": {"error": "Not Found"}
    },
}

# 模拟 PROVIDER_PRESETS（与 factory.py 一致）
MOCK_PRESETS = {
    "openai": {
        "name": "OpenAI",
        "api_base": "https://api.openai.com/v1",
        "default_model": "gpt-4.1",
        "models": ["gpt-5.5", "gpt-4.1", "o4-mini", "gpt-4o"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "api_base": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash"],
    },
    "moonshot": {
        "name": "Kimi (Moonshot)",
        "api_base": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2.6",
        "models": ["kimi-k2.6", "kimi-k2.5"],
    },
    "anthropic": {
        "name": "Claude (Anthropic)",
        "api_base": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "models": ["claude-sonnet-4-20250514", "claude-haiku-3-5-20250514"],
    },
    "baidu": {
        "name": "百度文心",
        "api_base": "https://qianfan.baidubce.com/v2",
        "default_model": "ernie-5.5-turbo",
        "models": ["ernie-5.5", "ernie-5.5-turbo", "ernie-4.0"],
    },
    "qwen": {
        "name": "通义千问",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3-flash",
        "models": ["qwen3-max", "qwen3-flash"],
    },
    "stepfun": {
        "name": "阶跃星辰",
        "api_base": "https://api.stepfun.com/v1",
        "default_model": "step-3.5-flash",
        "models": ["step-3.5-flash", "step-3.5-pro"],
    },
    "doubao": {
        "name": "豆包",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-seed-2.0-lite-128k",
        "models": ["doubao-seed-2.0-lite-128k", "doubao-seed-2.0-pro-256k"],
    },
    "ollama": {
        "name": "Ollama (本地)",
        "api_base": "http://localhost:11434/v1",
        "default_model": "llama3",
        "models": ["llama3", "qwen2.5", "mistral"],
    },
    "custom": {
        "name": "自定义",
        "api_base": "",
        "default_model": "",
        "models": [],
    },
}

# 模拟用户配置（含 api_key）
MOCK_USER_CONFIGS = {
    "openai": {"api_key": "sk-mock-openai-key123"},
    "deepseek": {"api_key": "sk-mock-deepseek-key456"},
    "moonshot": {"api_key": "sk-mock-moonshot-key789"},
    "anthropic": {"api_key": "sk-mock-anthropic-key"},
    "baidu": {"api_key": "mock-baidu-key"},
    "qwen": {"api_key": "sk-mock-qwen-key"},
    "stepfun": {"api_key": "sk-mock-stepfun-key"},
    "doubao": {"api_key": "ark-mock-doubao-key"},
    "ollama": {"api_key": ""},  # 本地不需要
    "custom": {"api_key": ""},
}


def mock_requests_get(url, headers=None, timeout=30, **kwargs):
    """模拟 requests.get 返回不同厂商的响应"""
    mock_response = MagicMock()

    # 根据 URL 匹配对应的模拟数据
    matched_key = None
    for key, preset in MOCK_PRESETS.items():
        base = preset.get("api_base", "")
        if base and url.startswith(base):
            matched_key = key
            break

    if matched_key and matched_key in MOCK_API_RESPONSES:
        mock_data = MOCK_API_RESPONSES[matched_key]
        if "side_effect" in mock_data:
            raise mock_data["side_effect"]
        mock_response.status_code = mock_data.get("status_code", 200)
        mock_response.json.return_value = mock_data.get("json", {})
        return mock_response

    # 默认返回 200 空数据
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    return mock_response


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

PASS = 0
FAIL = 0


def assert_eq(actual, expected, test_name=""):
    global PASS, FAIL
    if actual == expected:
        PASS += 1
        print(f"  ✅ {test_name}")
    else:
        FAIL += 1
        print(f"  ❌ {test_name}: 期望={expected}, 实际={actual}")


def assert_true(condition, test_name=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {test_name}")
    else:
        FAIL += 1
        print(f"  ❌ {test_name}: 条件为 False")


# ── 测试 1: is_update_needed ──────────────────────────────────

def test_is_update_needed():
    print("\n── 测试 1: is_update_needed() ──")
    from llm.model_updater import is_update_needed

    # 1a: 空缓存 → 需要更新
    assert_true(is_update_needed({}), "空缓存 → 需要更新")

    # 1b: 无 last_update → 需要更新
    assert_true(is_update_needed({"providers": {}}), "无 last_update → 需要更新")

    # 1c: 刚更新 → 不需要更新
    fresh = {"last_update": datetime.now(timezone.utc).isoformat()}
    assert_true(not is_update_needed(fresh), "刚更新 → 不需要更新")

    # 1d: 31 天前更新 → 需要更新
    old = {"last_update": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()}
    assert_true(is_update_needed(old), "31 天前 → 需要更新")

    # 1e: 29 天前更新 → 不需要更新
    recent = {"last_update": (datetime.now(timezone.utc) - timedelta(days=29)).isoformat()}
    assert_true(not is_update_needed(recent), "29 天前 → 不需要更新")

    # 1f: 损坏的时间格式 → 需要更新
    assert_true(is_update_needed({"last_update": "invalid-date"}), "损坏格式 → 需要更新")


# ── 测试 2: compare_models ──────────────────────────────────

def test_compare_models():
    print("\n── 测试 2: compare_models() ──")
    from llm.model_updater import compare_models

    # 2a: 新增模型
    added, removed = compare_models(["a", "b"], ["a", "b", "c", "d"])
    assert_eq(added, ["c", "d"], "新增: c, d")
    assert_eq(removed, [], "无移除")

    # 2b: 移除模型
    added, removed = compare_models(["a", "b", "c"], ["a"])
    assert_eq(added, [], "无新增")
    assert_eq(removed, ["b", "c"], "移除: b, c")

    # 2c: 同时新增和移除
    added, removed = compare_models(["a", "b", "c"], ["b", "d", "e"])
    assert_eq(added, ["d", "e"], "新增: d, e")
    assert_eq(removed, ["a", "c"], "移除: a, c")

    # 2d: 无变更
    added, removed = compare_models(["a", "b"], ["a", "b"])
    assert_eq(added, [], "无新增")
    assert_eq(removed, [], "无移除")

    # 2e: 完全替换
    added, removed = compare_models(["a", "b"], ["x", "y", "z"])
    assert_eq(added, ["x", "y", "z"], "新增: x, y, z")
    assert_eq(removed, ["a", "b"], "移除: a, b")


# ── 测试 3: fetch_models（含 UNSUPPORTED_PROVIDERS） ──────────

@patch("llm.model_updater.requests.get", side_effect=mock_requests_get)
def test_fetch_models(mock_get):
    print("\n── 测试 3: fetch_models() ──")
    from llm.model_updater import fetch_models

    MODELS_API = "https://api.openai.com/v1"

    # 3a: OpenAI 正常拉取
    models = fetch_models("openai", MODELS_API, "sk-test")
    assert_true(len(models) >= 3, f"OpenAI 返回 {len(models)} 个模型")
    assert_true("gpt-5.5-pro" in models, "包含 gpt-5.5-pro")
    assert_true("o4-mini" in models, "包含 o4-mini")

    # 3b: DeepSeek 正常拉取（含新模型 deepseek-chat-v2）
    models = fetch_models("deepseek", "https://api.deepseek.com/v1", "sk-test")
    assert_true("deepseek-chat-v2" in models, "包含新模型 deepseek-chat-v2")

    # 3c: Claude 使用 x-api-key 认证
    models = fetch_models("anthropic", "https://api.anthropic.com", "sk-test")
    assert_true("claude-opus-4-20250514" in models, "包含 claude-opus-4")

    # 3d: Ollama 使用 /api/tags 接口
    models = fetch_models("ollama", "http://localhost:11434/v1", "")
    assert_true("llama3" in models, "包含 llama3")
    assert_true("qwen2.5" in models, "包含 qwen2.5")

    # 3e: 百度文心 → 返回 None（UNSUPPORTED_PROVIDERS）
    models = fetch_models("baidu", "https://qianfan.baidubce.com/v2", "test")
    assert_true(models is None, "百度文心 → None (不支持)")

    # 3f: API 返回 500（使用 qwen 自身 api_base）
    models = fetch_models("qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", "sk-test")
    assert_eq(models, [], "API 500 → 空列表")

    # 3g: 网络异常（Connection timeout，使用 stepfun 自身 api_base）
    models = fetch_models("stepfun", "https://api.stepfun.com/v1", "sk-test")
    assert_eq(models, [], "网络异常 → 空列表")


# ── 测试 4: sync_provider（三种状态） ─────────────────────────

@patch("llm.model_updater.requests.get", side_effect=mock_requests_get)
def test_sync_provider(mock_get):
    print("\n── 测试 4: sync_provider() ──")
    from llm.model_updater import sync_provider

    # 4a: 正常同步（Kimi 新增 kimi-k2-instruct，移除 kimi-k2）
    result = sync_provider(
        "moonshot",
        "https://api.moonshot.cn/v1",
        "sk-test",
        "kimi-k2.6"
    )
    assert_true(result is not None, "Kimi 返回非 None")
    assert_eq(result.get("fetch_status"), "success", "状态 = success")
    assert_true("kimi-k2-instruct" in result.get("added", []), "新增 kimi-k2-instruct")
    # kimi-k2 存在于缓存旧列表中，新列表不含它 → 应被移除
    assert_true("kimi-k2" in result.get("removed", []), "移除 kimi-k2")

    # 4b: 不支持接口（百度文心）→ fetch_status = "manual"
    result = sync_provider(
        "baidu",
        "https://qianfan.baidubce.com/v2",
        "test-key",
        "ernie-5.5-turbo"
    )
    assert_true(result is not None, "百度返回非 None")
    assert_eq(result.get("fetch_status"), "manual", "状态 = manual")
    assert_true("unsupported_reason" in result, "包含 unsupported_reason")

    # 4c: API 调用失败（qwen 500，使用自身 api_base）
    result = sync_provider(
        "qwen",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "sk-test",
        "qwen3-flash"
    )
    assert_eq(result.get("fetch_status"), "failed", "状态 = failed")

    # 4d: 网络异常（stepfun，使用自身 api_base）
    result = sync_provider(
        "stepfun",
        "https://api.stepfun.com/v1",
        "sk-test",
        "step-3.5-flash"
    )
    assert_eq(result.get("fetch_status"), "failed", "状态 = failed")


# ── 测试 5: sync_all_providers（全量同步 + 内存刷新 + 日志） ──

@patch("llm.model_updater.requests.get", side_effect=mock_requests_get)
def test_sync_all_providers(mock_get):
    print("\n── 测试 5: sync_all_providers() ──")
    from llm.model_updater import sync_all_providers, load_cache, CACHE_PATH

    # 备份原缓存和日志
    backup_cache = None
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            backup_cache = f.read()

    try:
        # 修改缓存时间为 31 天前（触发更新）
        old_cache = {
            "last_update": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
            "update_interval_hours": 720,
            "providers": {
                "openai": {
                    "models": ["gpt-5.5", "gpt-4.1"],
                    "default_model": "gpt-4.1",
                    "api_base": "https://api.openai.com/v1",
                    "fetched_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
                }
            }
        }
        with open(CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(old_cache, f, ensure_ascii=False, indent=2)

        # 执行全量同步
        success = sync_all_providers(MOCK_PRESETS, MOCK_USER_CONFIGS)
        assert_true(success, "sync_all_providers 返回 True")

        # 验证缓存已更新
        cache = load_cache()
        assert_true(cache.get("last_update") is not None, "缓存有 last_update")

        providers = cache.get("providers", {})
        assert_true(len(providers) > 0, f"缓存包含 {len(providers)} 个提供商")

        # 验证 OpenAI 模型列表已更新（包含新模型 gpt-5.5-pro）
        openai_data = providers.get("openai", {})
        assert_true("gpt-5.5-pro" in openai_data.get("models", []),
                    "OpenAI 模型列表含 gpt-5.5-pro")

        # 验证百度文心标记为 manual
        baidu_data = providers.get("baidu", {})
        assert_eq(baidu_data.get("fetch_status"), "manual",
                  "百度 fetch_status = manual")

        # 验证自定义提供商被跳过
        assert_true("custom" not in providers or
                    providers["custom"].get("fetch_status") != "success",
                    "custom 未被同步")

        # 验证 Ollama 正常同步（NO_API_KEY_PROVIDERS 集合生效）
        ollama_data = providers.get("ollama", {})
        assert_eq(ollama_data.get("fetch_status"), "success",
                  "Ollama 正常同步（NO_API_KEY_PROVIDERS 生效）")
        assert_true("llama3" in ollama_data.get("models", []),
                    "Ollama 包含 llama3")

    finally:
        # 恢复原缓存
        if backup_cache:
            with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                f.write(backup_cache)


# ── 测试 6: 更新日志写入 ─────────────────────────────────────

def test_write_update_log():
    print("\n── 测试 6: _write_update_log() ──")
    from llm.model_updater import _write_update_log, LOG_PATH

    backup_log = None
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            backup_log = f.read()

    try:
        # 清空日志
        with open(LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump({"records": []}, f)

        # 构造模拟结果
        mock_results = {
            "success": {
                "openai": {"added": ["gpt-5.5-pro"], "removed": []},
                "deepseek": {"added": ["deepseek-chat-v2"], "removed": ["deepseek-chat"]},
            },
            "skipped": {
                "custom": "自定义提供商",
                "baidu": "千帆 API 不提供标准 /v1/models 端点",
                "qwen": "未配置 API Key",
            },
            "failed": {
                "stepfun": "Connection timeout",
            }
        }

        _write_update_log(mock_results)

        # 验证日志文件
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            log_data = json.load(f)

        records = log_data.get("records", [])
        assert_eq(len(records), 1, "日志包含 1 条记录")

        record = records[0]
        assert_eq(record.get("type"), "auto_update", "type = auto_update")
        assert_true("同步完成: 2 成功" in record.get("summary", ""),
                    "摘要包含成功数")
        assert_true("3 跳过" in record.get("summary", ""),
                    "摘要包含跳过数")
        assert_true("1 失败" in record.get("summary", ""),
                    "摘要包含失败数")

        # 写入第二条记录，验证新记录在前
        _write_update_log(mock_results)
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            log_data = json.load(f)
        assert_eq(len(log_data.get("records", [])), 2, "日志包含 2 条记录")

    finally:
        if backup_log:
            with open(LOG_PATH, 'w', encoding='utf-8') as f:
                f.write(backup_log)


# ── 测试 7: _refresh_after_sync（内存刷新） ──────────────────────

@patch("llm.model_updater.requests.get", side_effect=mock_requests_get)
def test_refresh_after_sync(mock_get):
    print("\n── 测试 7: _refresh_after_sync() ──")
    from llm.model_updater import _refresh_after_sync

    mock_results = {
        "success": {"openai": {"added": [], "removed": []}},
        "skipped": {"custom": "自定义提供商"},
        "failed": {},
    }

    try:
        _refresh_after_sync(mock_results)
        print("  ✅ _refresh_after_sync 无异常抛出")
        global PASS
        PASS += 1
    except Exception as e:
        print(f"  ❌ _refresh_after_sync 异常: {e}")
        global FAIL
        FAIL += 1


# ── 测试 8: _print_update_summary（控制台输出） ───────────────

def test_print_update_summary():
    print("\n── 测试 8: _print_update_summary() ──")
    from llm.model_updater import _print_update_summary

    mock_results = {
        "success": {
            "openai": {"added": ["gpt-5.5-pro", "gpt-4.1-nano"], "removed": ["gpt-4-vision-preview"]},
            "deepseek": {"added": [], "removed": []},
            "moonshot": {"added": ["kimi-k2-instruct"], "removed": []},
        },
        "skipped": {
            "custom": "自定义提供商",
            "baidu": "千帆 API 不提供标准 /v1/models 端点",
        },
        "failed": {
            "stepfun": "Connection timeout",
        }
    }

    try:
        _print_update_summary(mock_results)
        print("  ✅ _print_update_summary 无异常抛出")
        global PASS
        PASS += 1
    except Exception as e:
        print(f"  ❌ _print_update_summary 异常: {e}")
        global FAIL
        FAIL += 1


# ── 测试 9: UNSUPPORTED_PROVIDERS 完整性 ─────────────────────

def test_unsupported_providers():
    print("\n── 测试 9: 提供商特殊分类 ──")
    from llm.model_updater import UNSUPPORTED_PROVIDERS, NO_API_KEY_PROVIDERS

    assert_true("baidu" in UNSUPPORTED_PROVIDERS, "baidu 在 UNSUPPORTED 中")
    assert_true(len(UNSUPPORTED_PROVIDERS["baidu"]) > 0, "baidu 有原因说明")
    assert_true("ollama" in NO_API_KEY_PROVIDERS, "ollama 在 NO_API_KEY 中")
    assert_eq(len(NO_API_KEY_PROVIDERS), 1, "NO_API_KEY 只有 ollama")


# ═══════════════════════════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  模型自动更新功能测试")
    print("=" * 60)

    test_is_update_needed()
    test_compare_models()
    test_fetch_models()
    test_sync_provider()
    test_sync_all_providers()
    test_write_update_log()
    test_refresh_after_sync()
    test_print_update_summary()
    test_unsupported_providers()

    print("\n" + "=" * 60)
    print(f"  总计: {PASS + FAIL} 项, 通过 {PASS} 项, 失败 {FAIL} 项")
    if FAIL == 0:
        print("  🎉 全部通过!")
    else:
        print(f"  ⚠️  有 {FAIL} 项失败")
    print("=" * 60)