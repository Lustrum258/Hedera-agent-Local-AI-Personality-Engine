"""
Hedera 搜索提供者基类 + 注册表
"""

from typing import Protocol, Any


class SearchResult:
    title: str
    url: str
    snippet: str

    def __init__(self, title: str, url: str, snippet: str = ""):
        self.title = title
        self.url = url
        self.snippet = snippet

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class SearchResponse:
    success: bool
    results: list[SearchResult]
    source: str
    error: str
    note: str

    def __init__(self, success: bool = False, results: list = None,
                 source: str = "", error: str = "", note: str = ""):
        self.success = success
        self.results = results or []
        self.source = source
        self.error = error
        self.note = note

    def to_dict(self) -> dict:
        d = {"success": self.success, "source": self.source,
             "total": len(self.results), "results": [r.to_dict() for r in self.results]}
        if self.error:
            d["error"] = self.error
        if self.note:
            d["note"] = self.note
        return d


class BaseProvider(Protocol):
    """搜索提供者接口"""
    name: str

    def search(self, query: str, count: int = 5) -> SearchResponse:
        ...


# ─── 注册表 ───

_registry: dict[str, type[BaseProvider]] = {}


def register_provider(name: str, provider_cls: type[BaseProvider]):
    """注册一个搜索提供者"""
    _registry[name] = provider_cls


def get_provider(name: str) -> type[BaseProvider] | None:
    return _registry.get(name)


def list_providers() -> list[str]:
    return list(_registry.keys())


def build_providers_from_config(search_cfg: dict) -> list[tuple[int, BaseProvider]]:
    """
    从配置构建提供者实例列表。
    返回 [(priority, instance), ...]，按 priority 排序。
    """
    providers_cfg = search_cfg.get("providers", {})
    result = []

    for name, cfg in providers_cfg.items():
        if not cfg.get("enabled", False):
            continue

        cls = get_provider(name)
        if cls is None:
            continue

        # 解析 API Key
        api_key = cfg.get("api_key", "")
        key_env = cfg.get("api_key_env", "")
        if not api_key and key_env:
            import os
            api_key = os.environ.get(key_env, "")

        priority = cfg.get("priority", 50)
        try:
            instance = cls(api_key=api_key, config=cfg)
            result.append((priority, instance))
        except Exception:
            continue

    # 按 priority 排序
    result.sort(key=lambda x: x[0])
    return result
