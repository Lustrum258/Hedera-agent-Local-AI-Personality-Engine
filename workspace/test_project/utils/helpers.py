"""Utility functions"""
import hashlib
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional, TypeVar
from functools import wraps

T = TypeVar("T")


def retry(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0,
          exceptions: tuple = (Exception,)):
    """Retry decorator with exponential backoff"""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            current_delay = delay
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff
            raise last_exc
        return wrapper
    return decorator


def memoize(ttl: int = 300):
    """Simple in-memory cache with TTL"""
    def decorator(fn: Callable) -> Callable:
        cache: Dict[str, tuple] = {}

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = str(args) + str(sorted(kwargs.items()))
            now = time.time()
            if key in cache:
                result, timestamp = cache[key]
                if now - timestamp < ttl:
                    return result
            result = fn(*args, **kwargs)
            cache[key] = (result, now)
            return result

        wrapper.cache_clear = lambda: cache.clear()
        return wrapper
    return decorator


def slugify(text: str) -> str:
    """Convert text to URL-safe slug"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def deep_get(data: dict, path: str, default: Any = None) -> Any:
    """Get nested dict value by dot-notation path"""
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def deep_set(data: dict, path: str, value: Any):
    """Set nested dict value by dot-notation path"""
    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def flatten_dict(data: dict, prefix: str = "", sep: str = ".") -> dict:
    """Flatten nested dict"""
    result = {}
    for key, value in data.items():
        new_key = f"{prefix}{sep}{key}" if prefix else key
        if isinstance(value, dict):
            result.update(flatten_dict(value, new_key, sep))
        else:
            result[new_key] = value
    return result


def chunk_list(lst: list, size: int) -> list:
    """Split list into chunks"""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def deduplicate(lst: list, key: Callable = None) -> list:
    """Remove duplicates preserving order"""
    seen = set()
    result = []
    for item in lst:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result


def safe_json_loads(text: str, default: Any = None) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def generate_id(prefix: str = "", length: int = 8) -> str:
    """Generate a random ID"""
    import uuid
    uid = uuid.uuid4().hex[:length]
    return f"{prefix}{uid}" if prefix else uid


class Timer:
    """Context manager for timing code blocks"""
    def __init__(self, label: str = ""):
        self.label = label
        self.elapsed = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start
        if self.label:
            print(f"{self.label}: {self.elapsed:.4f}s")


class LRUCache:
    """Simple LRU cache"""
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self._cache: Dict[str, Any] = {}
        self._order: List[str] = []

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            self._order.remove(key)
            self._order.append(key)
            return self._cache[key]
        return None

    def set(self, key: str, value: Any):
        if key in self._cache:
            self._order.remove(key)
        elif len(self._cache) >= self.maxsize:
            oldest = self._order.pop(0)
            del self._cache[oldest]
        self._cache[key] = value
        self._order.append(key)

    def clear(self):
        self._cache.clear()
        self._order.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


class Pagination:
    """Pagination wrapper for query results"""
    def __init__(self, items: list, total: int, page: int, limit: int, offset: int):
        self.items = items
        self.total = total
        self.page = page
        self.limit = limit
        self.offset = offset

    @property
    def has_next(self) -> bool:
        return self.offset + self.limit < self.total

    @property
    def has_prev(self) -> bool:
        return self.offset > 0

    @property
    def total_pages(self) -> int:
        if self.limit <= 0:
            return 0
        import math
        return math.ceil(self.total / self.limit)

    def to_dict(self) -> dict:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "limit": self.limit,
            "offset": self.offset,
            "has_next": self.has_next,
            "has_prev": self.has_prev,
            "total_pages": self.total_pages
        }


def paginate(query: Any, page: Optional[int] = None, limit: Optional[int] = None, offset: Optional[int] = None) -> Pagination:
    """Paginate a QueryBuilder query
    
    Supports page/limit/offset, returns total count, and has has_next/has_prev helpers.
    """
    limit = limit if limit is not None else 10
    if limit <= 0:
        limit = 10

    if page is not None and offset is not None:
        offset = (page - 1) * limit
    elif page is not None:
        if page <= 0:
            page = 1
        offset = (page - 1) * limit
    elif offset is not None:
        if offset < 0:
            offset = 0
        page = (offset // limit) + 1
    else:
        page = 1
        offset = 0

    # Backup query state to prevent count() from altering it permanently
    original_select = query._select_cols
    original_limit = query._limit_val
    original_offset = query._offset_val

    # Get total count
    total = query.count()

    # Restore state and apply pagination limits
    query._select_cols = original_select
    query.limit(limit)
    query.offset(offset)

    items = query.all()

    # Restore original query limit/offset state to avoid side-effects on the query object
    query._limit_val = original_limit
    query._offset_val = original_offset

    return Pagination(items=items, total=total, page=page, limit=limit, offset=offset)

