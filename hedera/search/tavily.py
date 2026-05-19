"""Tavily API 搜索提供者"""

import os
import requests

from hedera.search.registry import BaseProvider, SearchResponse, SearchResult

_TAVILY_ENDPOINT = "https://api.tavily.com/search"


class TavilyProvider(BaseProvider):
    name = "tavily"

    def __init__(self, api_key: str = "", config: dict = None):
        self.api_key = api_key
        self.config = config or {}

    def search(self, query: str, count: int = 5) -> SearchResponse:
        if not self.api_key:
            return SearchResponse(success=False, source="tavily", error="API key 未设置")

        try:
            payload = {
                "api_key": self.api_key,
                "query": query,
                "search_depth": "advanced" if count > 5 else "basic",
                "max_results": count,
                "include_answer": False,
                "include_raw_content": False,
            }
            resp = requests.post(
                _TAVILY_ENDPOINT, json=payload, timeout=20,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            raw = data.get("results", [])
            if not raw:
                return SearchResponse(success=False, source="tavily", error="空结果")

            results = []
            for r in raw[:count]:
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=(r.get("content", "") or "")[:300],
                ))
            return SearchResponse(success=True, results=results, source="tavily")

        except requests.exceptions.Timeout:
            return SearchResponse(success=False, source="tavily", error="超时")
        except requests.exceptions.HTTPError as e:
            return SearchResponse(success=False, source="tavily",
                                  error=f"HTTP {e.response.status_code}")
        except Exception as e:
            return SearchResponse(success=False, source="tavily",
                                  error=str(e)[:80])
