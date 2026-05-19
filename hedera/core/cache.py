"""
Hedera 工具级 LRU 缓存
多步骤任务去重：同 URL、同搜索词、同文件路径，在 TTL 内直接命中。
"""

import time
import threading
from collections import OrderedDict


class LRUCache:
    """线程安全的 LRU 缓存，带 TTL 过期"""

    def __init__(self, capacity: int = 256, ttl: float = 300):
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self.capacity = capacity
        self.ttl = ttl
        # 统计
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: str) -> object | None:
        """获取缓存值。过期或不存在返回 None。"""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            value, expires = self._cache[key]
            if time.monotonic() > expires:
                del self._cache[key]
                self._evictions += 1
                self._misses += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: object, ttl: float | None = None):
        """写入缓存，可覆盖默认 TTL。"""
        expires = time.monotonic() + (ttl if ttl is not None else self.ttl)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, expires)
            while len(self._cache) > self.capacity:
                self._cache.popitem(last=False)
                self._evictions += 1

    def invalidate(self, key_prefix: str):
        """按前缀批量失效（例如 URL 域名变了的时候）。"""
        with self._lock:
            keys = [k for k in self._cache if k.startswith(key_prefix)]
            for k in keys:
                del self._cache[k]

    def clear(self):
        """清空缓存。"""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "capacity": self.capacity,
                "ttl": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0,
            }

    def __len__(self):
        with self._lock:
            return len(self._cache)


# ─── 全局缓存实例 ───────────

# 搜索结果缓存：同一搜索词短时间重复搜索直接命中
# TTL=180s（3分钟），搜索内容的时效性稍低没关系
search_cache = LRUCache(capacity=128, ttl=180)

# 网页抓取缓存：同一 URL 反复拉取
# TTL=600s（10分钟），网页内容在这个窗口内基本不变
fetch_cache = LRUCache(capacity=256, ttl=600)

# 文件读取缓存：同路径反复读取（如代码文件、配置文件）
# TTL=300s（5分钟），缓存包含文件 mtime，文件修改后自动失效
file_cache = LRUCache(capacity=128, ttl=300)
