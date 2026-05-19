"""Scrape fallback — Bing → 搜狗 → 360 爬虫引擎"""

import re
import os
from html.parser import HTMLParser
from urllib.parse import quote

import requests

from hedera.search.registry import BaseProvider, SearchResponse, SearchResult

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class _LinkExtractor(HTMLParser):
    """HTMLParser 状态机提取 Bing 搜索结果"""
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_h2 = self._in_a = self._in_li = self._in_p = False
        self._url = self._title = self._snip = self._href = ""

    def _s(self, t):
        return re.sub(r'\s+', ' ', t).strip()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "li" and "b_algo" in a.get("class", ""):
            self._in_li = True
            self._url = self._title = self._snip = ""
        if tag == "h2":
            self._in_h2 = True
        if self._in_h2 and tag == "a":
            self._in_a = True
            h = a.get("href", "")
            if h and h.startswith("http"):
                self._href = h
        if self._in_li and tag == "p":
            self._in_p = True

    def handle_data(self, data):
        if self._in_a:
            self._title += data
        if self._in_p:
            self._snip += data

    def handle_endtag(self, tag):
        if tag == "h2":
            self._in_h2 = False
        if self._in_a and tag == "a":
            self._in_a = False
            t = self._s(self._title)
            if t and len(t) > 2 and self._href:
                self._url = self._href
            self._href = ""
        if self._in_p and tag == "p":
            self._in_p = False
        if tag == "li" and self._in_li:
            self._in_li = False
            if self._url and self._title:
                self.results.append((self._s(self._title), self._url, self._s(self._snip)))


def _parse_bing(html: str) -> list[tuple]:
    p = _LinkExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    return p.results


def _fallback_h2(html: str, skip_domains: list = None) -> list[tuple]:
    skip = skip_domains or ["bing.com", "microsoft.com", "live.com"]
    seen, res = set(), []
    for m in re.finditer(r'<h2[^>]*>.*?<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>.*?</h2>',
                         html, re.DOTALL):
        import html as hmod
        u, t = m.group(1), hmod.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if t and len(t) > 3 and u not in seen and not any(d in u for d in skip):
            seen.add(u)
            res.append((t, u, ""))
    return res


def _strip_html(s: str) -> str:
    s = re.sub(r'<script[^>]*>.*?</script>', '', s, flags=re.DOTALL | re.I)
    s = re.sub(r'<style[^>]*>.*?</style>', '', s, flags=re.DOTALL | re.I)
    s = re.sub(r'<[^>]+>', '', s)
    import html as hmod
    s = hmod.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


class ScrapeProvider(BaseProvider):
    """爬虫搜索引擎，依次尝试 Bing → 搜狗 → 360"""
    name = "scrape"

    def __init__(self, api_key: str = "", config: dict = None):
        pass  # 爬虫不需要 API key

    def search(self, query: str, count: int = 5) -> SearchResponse:
        engines = [
            ("bing-cn", f"https://cn.bing.com/search?q={quote(query)}&count={count}", _parse_bing),
            ("bing-intl", f"https://www.bing.com/search?q={quote(query)}&count={count}", _parse_bing),
            ("sogou", f"https://www.sogou.com/web?query={quote(query)}", None),
            ("360", f"https://www.so.com/s?q={quote(query)}", None),
        ]

        last_err = ""
        for name, url, parser in engines:
            try:
                resp = requests.get(url, timeout=12, headers=_HEADERS, allow_redirects=True)
                resp.raise_for_status()

                raw = parser(resp.text) if parser else _fallback_h2(resp.text)
                if not raw:
                    raw = _fallback_h2(resp.text)

                if raw:
                    results = []
                    for title, url, snippet in raw[:count]:
                        results.append(SearchResult(title=title, url=url, snippet=snippet))
                    return SearchResponse(success=True, results=results, source=name)

                last_err = f"{name}: 无结果"
            except Exception as e:
                last_err = f"{name}: {str(e)[:60]}"
                continue

        # 终极兜底：原始文本
        try:
            fb = requests.get(
                f"https://cn.bing.com/search?q={quote(query)}",
                timeout=12, headers=_HEADERS
            )
            fb.raise_for_status()
            txt = _strip_html(fb.text)[:3000]
            if txt:
                return SearchResponse(
                    success=True,
                    source="bing-raw",
                    results=[SearchResult(
                        title="搜索完成",
                        url=f"https://cn.bing.com/search?q={quote(query)}",
                        snippet=txt,
                    )],
                    note="以下为搜索页原文，请自行提取有效信息",
                )
        except Exception:
            pass

        return SearchResponse(success=False, source="scrape",
                               error=f"搜索无结果 ({last_err})")
