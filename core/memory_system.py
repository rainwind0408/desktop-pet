"""
虚拟角色永久记忆系统
实现 FAISS 向量检索、AES 加密、记忆缓存、异步写入等核心功能

优化点：
1. SQLite 连接池 - 减少频繁开关连接
2. 摘要定时更新 - 批量处理，减少写入延迟
3. FAISS IndexIVFFlat - 提升大数据量检索性能
4. 动态缓存策略 - 基于访问频率调整
5. LLM 辅助重要性评估
6. 解密结果缓存
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np


# ---------------------------------------------------------------------------
# SQLite 连接池
# ---------------------------------------------------------------------------

class SQLiteConnectionPool:
    """SQLite 连接池，每个角色一个长连接"""

    def __init__(self, max_idle_time: float = 300):
        self._connections: Dict[str, sqlite3.Connection] = {}
        self._last_used: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_idle_time = max_idle_time

    def get_connection(self, db_path: str) -> sqlite3.Connection:
        """获取数据库连接，如果不存在或已过期则创建新连接"""
        with self._lock:
            now = time.time()
            conn = self._connections.get(db_path)

            # 检查连接是否存在且未过期
            if conn is not None:
                last_used = self._last_used.get(db_path, 0)
                if now - last_used < self._max_idle_time:
                    self._last_used[db_path] = now
                    return conn
                else:
                    # 连接过期，关闭并创建新的
                    try:
                        conn.close()
                    except Exception:
                        pass

            # 创建新连接
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式提升并发性能
            self._connections[db_path] = conn
            self._last_used[db_path] = now
            return conn

    def close_all(self):
        """关闭所有连接"""
        with self._lock:
            for conn in self._connections.values():
                try:
                    conn.close()
                except Exception:
                    pass
            self._connections.clear()
            self._last_used.clear()

    def cleanup_idle(self):
        """清理空闲连接"""
        with self._lock:
            now = time.time()
            expired = [
                path for path, last_used in self._last_used.items()
                if now - last_used >= self._max_idle_time
            ]
            for path in expired:
                conn = self._connections.pop(path, None)
                self._last_used.pop(path, None)
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass


# ---------------------------------------------------------------------------
# Embedding 提供者
# ---------------------------------------------------------------------------

class EmbeddingProvider:
    """统一 Embedding 接口，优先使用 API，降级到本地 n-gram 哈希"""

    EMBEDDING_DIM = 1536

    def __init__(self, llm_config: Optional[Dict] = None):
        self._api_key = ""
        self._api_base = ""
        self._model = "text-embedding-3-small"
        self._provider = ""
        self._use_api = False

        if llm_config:
            self._provider = llm_config.get("provider", "")
            self._api_key = llm_config.get("api_key", "")
            self._api_base = llm_config.get("api_base", "")
            model = llm_config.get("model", "")
            # 为各提供商选择合适的 embedding 模型
            embedding_models = {
                "openai": "text-embedding-3-small",
                "deepseek": "text-embedding-3-small",
                "qwen": "text-embedding-v3",
                "zhipu": "embedding-3",
                "custom": "text-embedding-3-small",
            }
            self._model = embedding_models.get(self._provider, "text-embedding-3-small")
            if self._api_key and self._provider != "ollama":
                self._use_api = True

        # n-gram 哈希 fallback 的维度
        self._hash_dim = self.EMBEDDING_DIM

    def embed(self, texts: List[str]) -> np.ndarray:
        if self._use_api:
            try:
                return self._embed_api(texts)
            except Exception:
                pass
        return self._embed_hash(texts)

    def embed_single(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    # -- API 调用 ----------------------------------------------------------
    def _embed_api(self, texts: List[str]) -> np.ndarray:
        import urllib.request

        api_base = self._api_base.rstrip("/")
        # 不同提供商的 embedding 端点
        if self._provider == "qwen":
            url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        elif self._provider == "zhipu":
            url = "https://open.bigmodel.cn/api/paas/v4/embeddings"
        else:
            url = f"{api_base}/embeddings"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        body = json.dumps({
            "model": self._model,
            "input": texts,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        embeddings = [item["embedding"] for item in data["data"]]
        return np.array(embeddings, dtype="float32")

    # -- 本地 n-gram 哈希 fallback -----------------------------------------
    def _embed_hash(self, texts: List[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            vec = np.zeros(self._hash_dim, dtype="float32")
            # 字符级 2-gram 和 3-gram
            for n in (2, 3):
                for i in range(len(text) - n + 1):
                    gram = text[i : i + n]
                    h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
                    idx = h % self._hash_dim
                    sign = 1 if (h >> 1) % 2 == 0 else -1
                    vec[idx] += sign
            # L2 归一化
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            vectors.append(vec)
        return np.array(vectors, dtype="float32")


# ---------------------------------------------------------------------------
# AES 加密工具（带解密缓存）
# ---------------------------------------------------------------------------

class MemoryEncryptor:
    """使用 Fernet (AES-128-CBC) 加密敏感记忆，支持解密缓存"""

    SENSITIVE_PATTERNS = [
        r"密码|password|passwd|口令",
        r"账号|account|用户名|username",
        r"手机|phone|电话|号码",
        r"地址|address|住址",
        r"身份证|id.?card|护照|passport",
        r"银行卡|bank.?card|信用卡|credit.?card",
    ]

    def __init__(self, key_dir: str = "characters"):
        self._fernet = None
        self._key_dir = key_dir
        self._decrypt_cache: Dict[str, str] = {}  # 加密内容 -> 解密内容
        self._cache_lock = threading.Lock()
        self._init_key()

    def _init_key(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            return

        key = os.environ.get("MEMORY_ENCRYPTION_KEY", "")
        if not key:
            key_path = os.path.join(self._key_dir, ".key")
            if os.path.exists(key_path):
                with open(key_path, "r") as f:
                    key = f.read().strip()
            else:
                key = Fernet.generate_key().decode()
                os.makedirs(self._key_dir, exist_ok=True)
                with open(key_path, "w") as f:
                    f.write(key)

        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception:
            self._fernet = None

    def is_sensitive(self, content: str) -> bool:
        for pattern in self.SENSITIVE_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    def encrypt(self, content: str) -> str:
        if not self._fernet:
            return content
        try:
            return self._fernet.encrypt(content.encode("utf-8")).decode("ascii")
        except Exception:
            return content

    def decrypt(self, content: str) -> str:
        """解密内容，使用缓存避免重复解密"""
        if not self._fernet:
            return content

        # 检查缓存
        with self._cache_lock:
            if content in self._decrypt_cache:
                return self._decrypt_cache[content]

        # 解密
        try:
            decrypted = self._fernet.decrypt(content.encode("ascii")).decode("utf-8")
        except Exception:
            return content

        # 缓存结果（限制缓存大小）
        with self._cache_lock:
            if len(self._decrypt_cache) > 1000:
                # 清理一半缓存
                keys = list(self._decrypt_cache.keys())
                for k in keys[:500]:
                    del self._decrypt_cache[k]
            self._decrypt_cache[content] = decrypted

        return decrypted

    def clear_cache(self):
        """清空解密缓存"""
        with self._cache_lock:
            self._decrypt_cache.clear()

    @property
    def available(self) -> bool:
        return self._fernet is not None


# ---------------------------------------------------------------------------
# 记忆系统主类
# ---------------------------------------------------------------------------

class MemorySystem:
    def __init__(self, characters_dir: str = "characters", llm_config: Optional[Dict] = None):
        self.characters_dir = characters_dir
        self.importance_threshold = 0.5
        self._llm_config = llm_config

        # 连接池
        self._conn_pool = SQLiteConnectionPool(max_idle_time=300)

        # 缓存管理（动态 TTL）
        self._memory_cache: Dict[str, List[Dict]] = {}
        self._cache_access_count: Dict[str, int] = defaultdict(int)
        self._cache_timestamps: Dict[str, float] = {}
        self._base_cache_ttl = 300  # 5 分钟基础 TTL
        self._max_cache_ttl = 1800  # 30 分钟最大 TTL

        # Embedding 和加密
        self.embedding_provider = EmbeddingProvider(llm_config)
        self.encryptor = MemoryEncryptor(characters_dir)

        # FAISS 索引管理
        self._faiss_indices: Dict[str, faiss.Index] = {}
        self._faiss_id_map: Dict[str, List[int]] = {}
        self._faiss_lock = threading.Lock()
        self._faiss_trained: Dict[str, bool] = {}  # 标记索引是否已训练

        # 摘要更新管理
        self._summary_dirty: Dict[str, bool] = {}  # 标记哪些角色需要更新摘要
        self._summary_timer: Optional[threading.Timer] = None
        self._summary_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 路径工具
    # ------------------------------------------------------------------

    def _get_db_path(self, character_id: str) -> str:
        return os.path.join(self.characters_dir, character_id, "memory_metadata.db")

    def _get_summary_path(self, character_id: str) -> str:
        return os.path.join(self.characters_dir, character_id, "memory_summary.txt")

    def _get_readable_summary_path(self, character_id: str) -> str:
        return os.path.join(self.characters_dir, character_id, "记忆摘要.txt")

    def _get_faiss_path(self, character_id: str) -> str:
        return os.path.join(self.characters_dir, character_id, "memory_index.faiss")

    # ------------------------------------------------------------------
    # 数据库初始化
    # ------------------------------------------------------------------

    def _ensure_db(self, character_id: str):
        db_path = self._get_db_path(character_id)
        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                encrypted INTEGER DEFAULT 0,
                role TEXT DEFAULT 'conversation',
                importance REAL DEFAULT 0.3,
                timestamp REAL NOT NULL,
                access_count INTEGER DEFAULT 0,
                last_access REAL,
                archived INTEGER DEFAULT 0
            )
        """)
        # 兼容旧数据库：添加缺失的 encrypted 列
        cursor.execute("PRAGMA table_info(memories)")
        columns = [col[1] for col in cursor.fetchall()]
        if "encrypted" not in columns:
            cursor.execute("ALTER TABLE memories ADD COLUMN encrypted INTEGER DEFAULT 0")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON memories(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_archived ON memories(archived)")
        conn.commit()

    # ------------------------------------------------------------------
    # FAISS 索引管理（支持 IVFFlat）
    # ------------------------------------------------------------------

    def _load_faiss_index(self, character_id: str) -> Tuple[faiss.Index, List[int]]:
        with self._faiss_lock:
            if character_id in self._faiss_indices:
                return self._faiss_indices[character_id], self._faiss_id_map[character_id]

            faiss_path = self._get_faiss_path(character_id)
            dim = self.embedding_provider.EMBEDDING_DIM

            if os.path.exists(faiss_path):
                try:
                    index = faiss.read_index(faiss_path)
                    # 从 SQLite 重建 id 映射
                    id_map = self._rebuild_id_map(character_id)
                    self._faiss_indices[character_id] = index
                    self._faiss_id_map[character_id] = id_map
                    self._faiss_trained[character_id] = True
                    return index, id_map
                except Exception:
                    pass

            # 创建新索引：先用 FlatIP，数据量大时自动切换到 IVFFlat
            index = faiss.IndexFlatIP(dim)
            self._faiss_indices[character_id] = index
            self._faiss_id_map[character_id] = []
            self._faiss_trained[character_id] = True  # FlatIP 不需要训练
            return index, []

    def _maybe_upgrade_to_ivf(self, character_id: str):
        """当数据量足够时，自动升级到 IVFFlat 索引"""
        with self._faiss_lock:
            index = self._faiss_indices.get(character_id)
            if index is None:
                return

            # 数据量超过 1000 且当前是 FlatIP 时升级
            if index.ntotal > 1000 and isinstance(index, faiss.IndexFlatIP):
                dim = self.embedding_provider.EMBEDDING_DIM
                nlist = min(100, index.ntotal // 10)  # 聚类数
                quantizer = faiss.IndexFlatIP(dim)
                new_index = faiss.IndexIVFFlat(quantizer, dim, nlist, faiss.METRIC_INNER_PRODUCT)

                # 获取所有向量进行训练
                vectors = faiss.rev_swig_ptr(index.get_xb(), index.ntotal * dim)
                vectors = vectors.reshape(index.ntotal, dim).copy()
                new_index.train(vectors)
                new_index.add(vectors)

                self._faiss_indices[character_id] = new_index
                self._faiss_trained[character_id] = True
                self._save_faiss_index(character_id)

    def _save_faiss_index(self, character_id: str):
        with self._faiss_lock:
            index = self._faiss_indices.get(character_id)
            if index is None:
                return
            faiss_path = self._get_faiss_path(character_id)
            os.makedirs(os.path.dirname(faiss_path), exist_ok=True)
            faiss.write_index(index, faiss_path)

    def _rebuild_id_map(self, character_id: str) -> List[int]:
        """从数据库重建 FAISS 索引对应的 rowid 映射"""
        db_path = self._get_db_path(character_id)
        if not os.path.exists(db_path):
            return []
        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM memories WHERE archived = 0 ORDER BY id"
        )
        ids = [row[0] for row in cursor.fetchall()]
        return ids

    def _rebuild_faiss_index(self, character_id: str):
        """从数据库重建完整 FAISS 索引（用于数据修复）"""
        db_path = self._get_db_path(character_id)
        if not os.path.exists(db_path):
            return

        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, content, encrypted FROM memories WHERE archived = 0 ORDER BY id"
        )
        rows = cursor.fetchall()

        dim = self.embedding_provider.EMBEDDING_DIM
        index = faiss.IndexFlatIP(dim)
        id_map = []

        texts = []
        row_ids = []
        for row in rows:
            content = row["content"]
            if row["encrypted"]:
                content = self.encryptor.decrypt(content)
            texts.append(content)
            row_ids.append(row["id"])

        if texts:
            vectors = self.embedding_provider.embed(texts)
            index.add(vectors)
            id_map = row_ids

        with self._faiss_lock:
            self._faiss_indices[character_id] = index
            self._faiss_id_map[character_id] = id_map
            self._faiss_trained[character_id] = True

        self._save_faiss_index(character_id)
        self._mark_summary_dirty(character_id)

    # ------------------------------------------------------------------
    # 重要性评估（支持 LLM 辅助）
    # ------------------------------------------------------------------

    def evaluate_importance(self, content: str, use_llm: bool = False) -> float:
        """评估记忆重要性，可选使用 LLM 辅助"""
        # 基于规则的快速评估
        importance_rules = [
            (r"生日|纪念日|重要|特别|结婚|毕业|入职", 0.9),
            (r"birthday|anniversary|important|special|wedding|graduation", 0.9),
            (r"喜欢|讨厌|过敏|害怕|最爱|最讨厌|偏好", 0.8),
            (r"love|hate|allergy|afraid|favorite|prefer|hate", 0.8),
            (r"家人|父母|爸爸|妈妈|兄弟|姐妹|朋友|恋人|伴侣", 0.8),
            (r"family|parent|father|mother|brother|sister|friend|partner", 0.8),
            (r"工作|学校|公司|大学|专业|职业", 0.7),
            (r"work|school|company|university|major|job|career", 0.7),
            (r"密码|账号|手机|电话|地址|身份证|银行卡", 0.9),
            (r"password|account|phone|address|bank", 0.9),
            (r"天气|温度|冷|热|下雨|下雪", 0.6),
            (r"weather|temperature|cold|hot|rain|snow", 0.6),
            (r"你好|再见|谢谢|晚安|早安|嗯|哦|好的", 0.2),
            (r"hello|bye|thanks|goodnight|goodmorning|ok|yes|no", 0.2),
        ]
        score = 0.3
        for pattern, weight in importance_rules:
            if re.search(pattern, content, re.IGNORECASE):
                score = max(score, weight)

        # 如果需要 LLM 辅助评估（仅对中等重要性的内容）
        if use_llm and 0.4 <= score <= 0.7 and self._llm_config:
            try:
                llm_score = self._evaluate_importance_with_llm(content)
                if llm_score is not None:
                    # 取规则和 LLM 评估的加权平均
                    score = score * 0.4 + llm_score * 0.6
            except Exception:
                pass

        return score

    def _evaluate_importance_with_llm(self, content: str) -> Optional[float]:
        """使用 LLM 评估内容重要性"""
        try:
            from llm import LLMFactory
            provider = LLMFactory.create(self._llm_config)
            prompt = f"""请评估以下对话内容的重要性（0.0-1.0）：
- 0.9-1.0: 重要个人信息（生日、纪念日、偏好、家人等）
- 0.7-0.8: 有价值的信息（工作、学校、兴趣等）
- 0.5-0.6: 一般信息（天气、日常等）
- 0.1-0.4: 寒暄、问候、无意义内容

内容：{content[:200]}

只返回一个数字，不要其他内容。"""

            response = provider.chat([{"role": "user", "content": prompt}])
            # 提取数字
            match = re.search(r"(\d+\.?\d*)", response)
            if match:
                score = float(match.group(1))
                return max(0.1, min(1.0, score))
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 缓存管理（动态 TTL）
    # ------------------------------------------------------------------

    def _get_cache_ttl(self, character_id: str) -> float:
        """根据访问频率动态调整缓存 TTL"""
        access_count = self._cache_access_count.get(character_id, 0)
        # 访问越多，缓存时间越长
        ttl = self._base_cache_ttl * (1 + access_count * 0.1)
        return min(ttl, self._max_cache_ttl)

    def _get_cache(self, character_id: str) -> Optional[List[Dict]]:
        ts = self._cache_timestamps.get(character_id, 0)
        ttl = self._get_cache_ttl(character_id)
        if time.time() - ts < ttl:
            self._cache_access_count[character_id] += 1
            return self._memory_cache.get(character_id)
        return None

    def _set_cache(self, character_id: str, memories: List[Dict]):
        self._memory_cache[character_id] = memories
        self._cache_timestamps[character_id] = time.time()

    def _invalidate_cache(self, character_id: str):
        self._memory_cache.pop(character_id, None)
        self._cache_timestamps.pop(character_id, None)
        self._cache_access_count.pop(character_id, None)

    # ------------------------------------------------------------------
    # 摘要管理（延迟更新）
    # ------------------------------------------------------------------

    def _mark_summary_dirty(self, character_id: str):
        """标记角色摘要需要更新"""
        with self._summary_lock:
            self._summary_dirty[character_id] = True
            # 启动定时器，延迟更新摘要
            if self._summary_timer is None or not self._summary_timer.is_alive():
                self._summary_timer = threading.Timer(10.0, self._flush_dirty_summaries)
                self._summary_timer.daemon = True
                self._summary_timer.start()

    def _flush_dirty_summaries(self):
        """批量更新所有标记为 dirty 的摘要"""
        with self._summary_lock:
            dirty_ids = [cid for cid, dirty in self._summary_dirty.items() if dirty]
            self._summary_dirty.clear()

        for character_id in dirty_ids:
            try:
                self._sync_readable_summary(character_id)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 记忆写入
    # ------------------------------------------------------------------

    def add_memory(self, character_id: str, content: str, role: str = "conversation") -> bool:
        importance = self.evaluate_importance(content)
        if importance < self.importance_threshold:
            return False

        self._ensure_db(character_id)
        db_path = self._get_db_path(character_id)

        # 判断是否需要加密
        is_enc = self.encryptor.is_sensitive(content)
        stored_content = self.encryptor.encrypt(content) if is_enc else content

        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (content, encrypted, role, importance, timestamp) VALUES (?, ?, ?, ?, ?)",
            (stored_content, 1 if is_enc else 0, role, importance, time.time()),
        )
        row_id = cursor.lastrowid
        conn.commit()

        # 更新 FAISS 索引
        try:
            index, id_map = self._load_faiss_index(character_id)
            vector = self.embedding_provider.embed_single(content)
            with self._faiss_lock:
                index.add(vector.reshape(1, -1))
                id_map.append(row_id)
            self._save_faiss_index(character_id)
            # 检查是否需要升级索引
            self._maybe_upgrade_to_ivf(character_id)
        except Exception:
            pass

        self._invalidate_cache(character_id)

        # 延迟更新摘要（而非立即更新）
        self._mark_summary_dirty(character_id)

        return True

    def add_memory_async(self, character_id: str, content: str, role: str = "conversation"):
        threading.Thread(
            target=self.add_memory,
            args=(character_id, content, role),
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # 记忆检索
    # ------------------------------------------------------------------

    def retrieve_memories(
        self,
        character_id: str,
        query: str = "",
        top_k: int = 5,
    ) -> List[Dict]:
        # 尝试从缓存获取
        cached = self._get_cache(character_id)
        if cached and not query:
            return cached[:top_k]

        self._ensure_db(character_id)
        db_path = self._get_db_path(character_id)

        # 向量检索
        vector_results = self._vector_search(character_id, query, top_k * 3) if query else []

        # 数据库检索（作为补充）
        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()

        if vector_results:
            ids = [r["id"] for r in vector_results]
            placeholders = ",".join("?" * len(ids))
            cursor.execute(
                f"SELECT id, content, encrypted, role, importance, timestamp, access_count "
                f"FROM memories WHERE archived = 0 AND id IN ({placeholders})",
                ids,
            )
        else:
            cursor.execute(
                "SELECT id, content, encrypted, role, importance, timestamp, access_count "
                "FROM memories WHERE archived = 0 ORDER BY importance DESC, timestamp DESC LIMIT ?",
                (top_k * 3,),
            )

        rows = cursor.fetchall()
        now = time.time()
        memories = []

        # 向量分数映射
        vector_score_map = {r["id"]: r["score"] for r in vector_results}

        for row in rows:
            age_days = (now - row["timestamp"]) / 86400
            time_decay = max(0.1, 1.0 - age_days / 365)

            # 向量相似度得分
            vec_score = vector_score_map.get(row["id"], 0.0)

            # 关键词匹配加权
            keyword_bonus = 0.0
            if query:
                content = row["content"]
                if row["encrypted"]:
                    content = self.encryptor.decrypt(content)
                if query in content:
                    keyword_bonus = 0.3

            # 综合得分：向量相似度 50% + 时间衰减 20% + 重要性 20% + 关键词 10%
            if vec_score > 0:
                score = vec_score * 0.5 + time_decay * 0.2 + row["importance"] * 0.2 + keyword_bonus * 0.1
            else:
                score = row["importance"] * 0.5 + time_decay * 0.3 + keyword_bonus * 0.2

            content = row["content"]
            if row["encrypted"]:
                content = self.encryptor.decrypt(content)

            memories.append({
                "id": row["id"],
                "content": content,
                "role": row["role"],
                "importance": row["importance"],
                "timestamp": row["timestamp"],
                "score": score,
            })

            cursor.execute(
                "UPDATE memories SET access_count = access_count + 1, last_access = ? WHERE id = ?",
                (now, row["id"]),
            )

        conn.commit()

        memories.sort(key=lambda x: x["score"], reverse=True)
        result = memories[:top_k]

        if not query:
            self._set_cache(character_id, result)

        return result

    def _vector_search(self, character_id: str, query: str, top_k: int) -> List[Dict]:
        try:
            index, id_map = self._load_faiss_index(character_id)
            if index.ntotal == 0 or not id_map:
                return []

            query_vec = self.embedding_provider.embed_single(query).reshape(1, -1)
            k = min(top_k, index.ntotal)

            # 如果是 IVFFlat，设置 nprobe
            if isinstance(index, faiss.IndexIVFFlat):
                index.nprobe = min(10, index.nlist)

            distances, indices = index.search(query_vec, k)

            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < 0 or idx >= len(id_map):
                    continue
                results.append({
                    "id": id_map[idx],
                    "score": float(dist),
                })
            return results
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 记忆 Prompt 构建
    # ------------------------------------------------------------------

    def build_memory_prompt(self, character_id: str, user_input: str = "") -> str:
        relevant_memories = self.retrieve_memories(character_id, user_input)
        if not relevant_memories:
            return ""

        memory_prompt = "[长期记忆]\n"
        for memory in relevant_memories:
            dt = datetime.fromtimestamp(memory["timestamp"]).strftime("%Y-%m-%d")
            memory_prompt += f"- {memory['content']} (记录于: {dt})\n"

        memory_prompt += "\n[行为指导]\n"
        memory_prompt += "请在回复中自然地引用这些记忆，不要生硬提及，要像真正记得这些事一样。"
        return memory_prompt

    # ------------------------------------------------------------------
    # 记忆摘要
    # ------------------------------------------------------------------

    def _sync_readable_summary(self, character_id: str):
        """生成人类可读的记忆摘要文件"""
        self._ensure_db(character_id)
        db_path = self._get_db_path(character_id)

        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT content, encrypted, role, importance, timestamp, access_count "
            "FROM memories WHERE archived = 0 ORDER BY importance DESC, timestamp DESC"
        )
        rows = cursor.fetchall()

        cursor.execute("SELECT COUNT(*) FROM memories WHERE archived = 1")
        archived_count = cursor.fetchone()[0]

        now = datetime.now()
        lines = []
        lines.append("=" * 60)
        lines.append(f"  记忆摘要 - {character_id}")
        lines.append(f"  生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  活跃记忆: {len(rows)} 条 | 已归档: {archived_count} 条")
        lines.append("=" * 60)
        lines.append("")

        if not rows:
            lines.append("  （暂无记忆记录）")
        else:
            # 按重要性分组
            high = []      # >= 0.8
            medium = []    # >= 0.5
            low = []       # < 0.5

            for row in rows:
                content = row["content"]
                if row["encrypted"]:
                    content = self.encryptor.decrypt(content)
                    # 脱敏显示
                    content = self._desensitize_for_display(content)

                importance = row["importance"]
                ts = row["timestamp"]
                dt = datetime.fromtimestamp(ts)
                age_days = (now.timestamp() - ts) / 86400

                entry = {
                    "content": content,
                    "importance": importance,
                    "datetime": dt.strftime("%Y-%m-%d %H:%M"),
                    "age_days": int(age_days),
                    "access_count": row["access_count"],
                    "role": row["role"],
                }

                if importance >= 0.8:
                    high.append(entry)
                elif importance >= 0.5:
                    medium.append(entry)
                else:
                    low.append(entry)

            importance_labels = {
                "high": ("核心记忆（重要性 >= 0.8）", high),
                "medium": ("普通记忆（重要性 >= 0.5）", medium),
                "low": ("日常记忆（重要性 < 0.5）", low),
            }

            for key in ("high", "medium", "low"):
                label, entries = importance_labels[key]
                if not entries:
                    continue

                lines.append(f"【{label}】共 {len(entries)} 条")
                lines.append("-" * 40)

                for i, entry in enumerate(entries, 1):
                    role_tag = "用户" if entry["role"] == "user" else "AI"
                    age_str = (
                        "今天" if entry["age_days"] == 0
                        else f"{entry['age_days']}天前"
                    )
                    lines.append(
                        f"  {i}. [{role_tag}] {entry['content']}"
                    )
                    lines.append(
                        f"     时间: {entry['datetime']} | {age_str}"
                        f" | 重要性: {entry['importance']:.1f}"
                        f" | 被回忆: {entry['access_count']}次"
                    )
                    lines.append("")

        lines.append("-" * 60)
        lines.append("  说明: 此文件由记忆系统自动生成，每次新记忆写入后延迟更新。")
        lines.append("  加密记忆已脱敏显示，完整内容存储在 memory_metadata.db 中。")
        lines.append("=" * 60)

        summary_text = "\n".join(lines)

        summary_path = self._get_readable_summary_path(character_id)
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary_text)

    def _desensitize_for_display(self, content: str) -> str:
        """对敏感内容脱敏后显示"""
        # 替换密码类内容（密码关键词 + is/是/为 + 后续值）
        content = re.sub(
            r"((?:密码|password|passwd|口令)\s*(?:is|是|为|:|：)?\s*)\S+",
            r"\1******",
            content,
            flags=re.IGNORECASE,
        )
        # 替换手机号
        content = re.sub(
            r"1[3-9]\d{9}",
            "1**********",
            content,
        )
        # 替换银行卡号
        content = re.sub(
            r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}",
            "****-****-****-****",
            content,
        )
        # 替换身份证号（18位）
        content = re.sub(
            r"\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
            "*******************",
            content,
        )
        return content

    def generate_memory_summary(self, character_id: str, llm_call=None) -> str:
        recent_memories = self.retrieve_memories(character_id, top_k=50)
        if not recent_memories:
            return "暂无记忆记录。"

        if llm_call:
            summary_prompt = f"""请为以下对话记录生成一个简洁的摘要，保留核心信息：
{chr(10).join([m['content'] for m in recent_memories])}

摘要要求：
1. 保留用户的重要个人信息
2. 记录关键事件和时间节点
3. 简洁明了，不超过100字"""
            summary = llm_call(summary_prompt)
        else:
            contents = [m["content"] for m in recent_memories[:10]]
            summary = f"记忆摘要（共{len(recent_memories)}条记录）：\n" + "\n".join(
                f"- {c[:50]}..." if len(c) > 50 else f"- {c}" for c in contents
            )

        summary_path = self._get_summary_path(character_id)
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary)

        return summary

    # ------------------------------------------------------------------
    # 记忆清理
    # ------------------------------------------------------------------

    def cleanup_old_memories(
        self,
        character_id: str,
        max_age_days: int = 365,
        importance_threshold: float = 0.4,
    ) -> int:
        self._ensure_db(character_id)
        db_path = self._get_db_path(character_id)
        cutoff_time = time.time() - max_age_days * 86400

        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE memories SET archived = 1 WHERE timestamp < ? AND importance < ? AND archived = 0",
            (cutoff_time, importance_threshold),
        )
        count = cursor.rowcount
        conn.commit()

        if count > 0:
            self._invalidate_cache(character_id)
            self._rebuild_faiss_index(character_id)

        return count

    def delete_character_memories(self, character_id: str) -> bool:
        db_path = self._get_db_path(character_id)
        summary_path = self._get_summary_path(character_id)
        readable_summary_path = self._get_readable_summary_path(character_id)
        faiss_path = self._get_faiss_path(character_id)

        for path in (db_path, summary_path, readable_summary_path, faiss_path):
            if os.path.exists(path):
                os.remove(path)

        self._invalidate_cache(character_id)
        with self._faiss_lock:
            self._faiss_indices.pop(character_id, None)
            self._faiss_id_map.pop(character_id, None)
            self._faiss_trained.pop(character_id, None)
        return True

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_memory_stats(self, character_id: str) -> Dict:
        self._ensure_db(character_id)
        db_path = self._get_db_path(character_id)

        conn = self._conn_pool.get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM memories WHERE archived = 0")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT AVG(importance) FROM memories WHERE archived = 0")
        avg_importance = cursor.fetchone()[0] or 0

        cursor.execute(
            "SELECT COUNT(*) FROM memories WHERE archived = 0 AND timestamp > ?",
            (time.time() - 7 * 86400,),
        )
        recent = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM memories WHERE archived = 1")
        archived = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM memories WHERE encrypted = 1 AND archived = 0")
        encrypted = cursor.fetchone()[0]

        with self._faiss_lock:
            faiss_total = self._faiss_indices.get(character_id, faiss.IndexFlatIP(1)).ntotal if character_id in self._faiss_indices else 0

        return {
            "total_memories": total,
            "average_importance": round(avg_importance, 2),
            "recent_week": recent,
            "archived": archived,
            "encrypted": encrypted,
            "faiss_vectors": faiss_total,
            "cache_hit": character_id in self._memory_cache,
            "cache_ttl": self._get_cache_ttl(character_id),
        }

    # ------------------------------------------------------------------
    # 清理资源
    # ------------------------------------------------------------------

    def cleanup(self):
        """清理资源，在程序退出时调用"""
        # 刷新所有待更新的摘要
        self._flush_dirty_summaries()
        # 清理空闲连接
        self._conn_pool.cleanup_idle()
        # 清空解密缓存
        self.encryptor.clear_cache()
