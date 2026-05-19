"""Hedera 搜索入口 — 多 provider 自动调度"""

from hedera.search.registry import (
    register_provider, build_providers_from_config, SearchResponse
)
from hedera.search.tavily import TavilyProvider
from hedera.search.scrape import ScrapeProvider

def _load_config_from_cwd() -> dict | None:
    """从当前目录的 config.yaml 加载搜索配置"""
    import os
    cwd = os.getcwd()
    candidates = [
        os.path.join(cwd, "config.yaml"),
        os.path.join(cwd, "config", "default.yaml"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                import yaml
                with open(path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f)
            except Exception:
                pass
    return None


# 注册内置 provider
register_provider("tavily", TavilyProvider)
register_provider("scrape", ScrapeProvider)


# 未来可以加更多 provider，在 import 时自动注册
# from hedera.search.brave import BraveProvider
# register_provider("brave", BraveProvider)


def search(query: str, count: int = 5, config: dict = None) -> dict:
    """
    统一搜索入口。
    按 priority 遍历配置中的 provider，第一个成功的返回。
    全部失败则返回最后的失败结果。
    如果未传入 config，自动尝试从当前目录的 config.yaml 加载。
    """
    if config is None:
        config = _load_config_from_cwd()
    if config is None:
        config = {}

    search_cfg = config.get("search", {})
    providers = build_providers_from_config(search_cfg)

    if not providers:
        # 没有任何 provider 启用 → 用爬虫兜底
        scrape = ScrapeProvider()
        resp = scrape.search(query, count)
        return resp.to_dict()

    last_resp = SearchResponse(success=False, error="无可用 provider")

    for priority, provider in providers:
        try:
            resp = provider.search(query, count)
            if resp.success and resp.results:
                return resp.to_dict()
            last_resp = resp
        except Exception as e:
            last_resp = SearchResponse(success=False, source=provider.name,
                                        error=str(e)[:80])
            continue

    return last_resp.to_dict()
