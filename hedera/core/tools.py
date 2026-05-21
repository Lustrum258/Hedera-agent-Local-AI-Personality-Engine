"""
Hedera 工具系统
结构化工具调用，插件架构。
"""

import os, sys, json, subprocess, re, threading, uuid, urllib, html as html_mod
from html.parser import HTMLParser
from typing import Callable

from hedera.core.cache import search_cache, fetch_cache, file_cache
from hedera.core.sanitizer import (
    validate_shell_command, truncate_output,
    validate_read_path, validate_write_path,
    validate_url, run_plugin_safe,
)

# ─── 并发锁 ───────────
_tools_lock = threading.Lock()
_file_io_lock = threading.Lock()

# ─── 文件上传目录（由 HTTP 服务设置） ───
_uploads_dir: str = ""

def set_uploads_dir(path: str):
    """设置上传目录（供 HTTP handler 调用）"""
    global _uploads_dir
    _uploads_dir = path


def _send_existing_file(source_path: str, display_name: str = "") -> dict:
    """把服务器上已有的文件拷贝到上传目录，返回下载 URL"""
    if not _uploads_dir:
        return {"success": False, "error": "上传目录未配置"}
    if not source_path:
        return {"success": False, "error": "文件路径不能为空"}
    source_path = os.path.normpath(source_path)
    if not os.path.isfile(source_path):
        return {"success": False, "error": f"文件不存在: {source_path}"}
    safe_name = display_name or os.path.basename(source_path)
    if not safe_name:
        safe_name = f"file_{uuid.uuid4().hex[:8]}"
    sess_dir = os.path.join(_uploads_dir, "_common")
    os.makedirs(sess_dir, exist_ok=True)
    dest_path = os.path.join(sess_dir, safe_name)
    if os.path.exists(dest_path):
        base, ext = os.path.splitext(safe_name)
        n = 1
        while os.path.exists(os.path.join(sess_dir, f"{base}_{n}{ext}")):
            n += 1
        safe_name = f"{base}_{n}{ext}"
        dest_path = os.path.join(sess_dir, safe_name)
    try:
        import shutil
        shutil.copy2(source_path, dest_path)
        file_size = os.path.getsize(dest_path)
        url = f"/download/_common/{safe_name}"
        return {
            "success": True,
            "file": safe_name,
            "size": file_size,
            "url": url,
            "source": source_path,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _create_download_file(filename: str, content: str, server_url: str = "http://112.17.187.18:36313") -> dict:
    """写文件到上传目录，返回下载 URL（供 AI 生成文件发给用户）"""
    if not _uploads_dir:
        return {"success": False, "error": "上传目录未配置，不可用"}
    if not filename or not content:
        return {"success": False, "error": "文件名和内容不能为空"}
    safe_name = os.path.basename(filename)
    if not safe_name:
        safe_name = f"file_{uuid.uuid4().hex[:8]}.txt"
    sess_dir = os.path.join(_uploads_dir, "_common")
    os.makedirs(sess_dir, exist_ok=True)
    save_path = os.path.join(sess_dir, safe_name)
    if os.path.exists(save_path):
        base, ext = os.path.splitext(safe_name)
        n = 1
        while os.path.exists(os.path.join(sess_dir, f"{base}_{n}{ext}")):
            n += 1
        safe_name = f"{base}_{n}{ext}"
        save_path = os.path.join(sess_dir, safe_name)
    try:
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(content)
        # 返回完整URL，方便用户直接点击
        url = f"/download/_common/{safe_name}"
        full_url = f"{server_url.rstrip('/')}{url}"
        return {
            "success": True,
            "file": safe_name,
            "size": len(content.encode("utf-8")),
            "url": full_url,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}



def _exec_shell(cmd: str, timeout: int = 30) -> dict:
    # 输入校验
    validation = validate_shell_command(cmd, timeout)
    if validation is not None:
        return validation
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                timeout=timeout, encoding="utf-8", errors="replace")
        # 执行完成后清理临时脚本文件
        _cleanup_temp_scripts()
        return {
            "stdout": truncate_output(result.stdout),
            "stderr": truncate_output(result.stderr),
            "returncode": result.returncode,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        _cleanup_temp_scripts()
        return {"stdout": "", "stderr": f"超时（{timeout}s）", "returncode": -1, "success": False}
    except Exception as e:
        _cleanup_temp_scripts()
        return {"stdout": "", "stderr": str(e), "returncode": -1, "success": False}


def _cleanup_temp_scripts():
    """清理项目根目录下的临时脚本文件"""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    patterns = ["test_*.py", "fix_*.py", "check_*.py", "cleanup*.py",
                "add_*.py", "remove_*.py", "move_*.py", "rm_*.py"]
    import glob
    for pat in patterns:
        for f in glob.glob(os.path.join(project_dir, pat)):
            try:
                os.remove(f)
            except Exception:
                pass


def _write_file(path: str, content: str) -> dict:
    """原子写入：先写 .tmp 再 rename，崩溃不影响原文件"""
    abs_path = validate_write_path(path)
    if abs_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    with _file_io_lock:
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            tmp_path = abs_path + ".hedera_tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, abs_path)
            # 清理残留 .tmp
            for leftover in [abs_path + ".hedera_tmp"]:
                if os.path.exists(leftover):
                    try:
                        os.remove(leftover)
                    except Exception:
                        pass
            return {"success": True, "path": abs_path}
        except Exception as e:
            return {"success": False, "error": str(e)}


def _read_file(path: str) -> dict:
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    # 缓存键包含文件 mtime → 文件修改后自动失效
    try:
        mtime = os.path.getmtime(safe_path)
    except Exception:
        mtime = 0
    cache_key = f"file:{safe_path}:{mtime}"
    cached = file_cache.get(cache_key)
    if cached is not None:
        return cached
    with _file_io_lock:
        try:
            with open(safe_path, "r", encoding="utf-8") as f:
                content = f.read()
            result = {"success": True, "content": content}
            file_cache.set(cache_key, result)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}


def _list_dir(path: str) -> dict:
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    with _file_io_lock:
        try:
            items = []
            for item in sorted(os.listdir(safe_path)):
                full = os.path.join(path, item)
                items.append({"name": item,
                              "type": "dir" if os.path.isdir(full) else "file",
                              "size": os.path.getsize(full) if not os.path.isdir(full) else 0})
            return {"success": True, "path": path, "items": items}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ─── 搜索 ───────────

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_BLOCKED = ["baidu.com", "tieba.baidu.com", "zhidao.baidu.com"]
_TAVILY_ENDPOINT = "https://api.tavily.com/search"


class _LinkExtractor(HTMLParser):
    """HTMLParser 状态机提取 Bing 搜索结果"""
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_h2 = self._in_h2_a = self._in_res = self._in_p = False
        self._url = self._title = self._snippet = self._href = ""

    def _s(self, t):
        return re.sub(r'\s+', ' ', t).strip()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "li" and "b_algo" in a.get("class", ""):
            self._in_res = True
            self._url = self._title = self._snippet = ""
        if tag == "h2":
            self._in_h2 = True
        if self._in_h2 and tag == "a":
            self._in_h2_a = True
            h = a.get("href", "")
            if h and h.startswith("http"):
                self._href = h
        if self._in_res and tag == "p":
            self._in_p = True

    def handle_data(self, data):
        if self._in_h2_a:
            self._title += data
        if self._in_p:
            self._snippet += data

    def handle_endtag(self, tag):
        if tag == "h2":
            self._in_h2 = False
        if self._in_h2_a and tag == "a":
            self._in_h2_a = False
            t = self._s(self._title)
            if t and len(t) > 2 and self._href:
                self._url = self._href
            self._href = ""
        if self._in_p and tag == "p":
            self._in_p = False
        if tag == "li" and self._in_res:
            self._in_res = False
            if self._url and self._title:
                self.results.append({"title": self._s(self._title), "url": self._url,
                                     "snippet": self._s(self._snippet)})
            self._url = self._title = self._snippet = ""


def _parse_bing(html: str, max_n: int) -> list:
    p = _LinkExtractor()
    try:
        p.feed(html)
    except Exception:
        pass
    return p.results[:max_n]


def _fallback_links(html: str, max_n: int, skip=None) -> list:
    skip = skip or ["bing.com", "microsoft.com", "live.com"]
    seen, res = set(), []
    for m in re.finditer(r'<h2[^>]*>.*?<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>.*?</h2>',
                         html, re.DOTALL):
        u, t = m.group(1), html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if t and len(t) > 3 and u not in seen and not any(d in u for d in skip):
            seen.add(u)
            res.append({"title": t, "url": u, "snippet": ""})
        if len(res) >= max_n:
            break
    return res


def _strip_html(s: str) -> str:
    s = re.sub(r'<script[^>]*>.*?</script>', '', s, flags=re.DOTALL | re.I)
    s = re.sub(r'<style[^>]*>.*?</style>', '', s, flags=re.DOTALL | re.I)
    s = re.sub(r'<[^>]+>', '', s)
    s = html_mod.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def _get_tavily_key() -> str:
    key = os.environ.get("TAVILY_API_KEY", "")
    if key:
        return key
    try:
        import yaml
        for p in [os.path.join(os.getcwd(), "config.yaml"),
                  os.path.join(os.path.dirname(__file__), "..", "default.yaml")]:
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    d = yaml.safe_load(f)
                key = d.get("search", {}).get("tavily_api_key", "")
                if key:
                    break
    except Exception:
        pass
    return key


def _tavily_search(query: str, count: int = 5) -> dict:
    api_key = _get_tavily_key()
    if not api_key:
        return {"success": False, "error": "key 未设置", "skip_fallback": False}
    try:
        import requests
        payload = {"api_key": api_key, "query": query,
                   "search_depth": "advanced" if count > 5 else "basic",
                   "max_results": count, "include_answer": False, "include_raw_content": False}
        resp = requests.post(_TAVILY_ENDPOINT, json=payload, timeout=20,
                             headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("results", [])
        if not raw:
            return {"success": False, "error": "Tavily 空结果", "skip_fallback": False}
        results = [{"title": r.get("title", ""), "url": r.get("url", ""),
                     "snippet": (r.get("content", "") or "")[:300]} for r in raw[:count]]
        return {"success": True, "results": results, "source": "tavily", "total": len(results)}
    except Exception as e:
        return {"success": False, "error": f"Tavily: {str(e)[:80]}", "skip_fallback": True}


def _web_fetch(url: str) -> dict:
    safe_url = validate_url(url)
    if safe_url is None:
        return {"success": False, "error": "URL 被阻止或不合法"}
    url = safe_url
    for b in _BLOCKED:
        if b in url.lower():
            return {"success": False, "error": f"无法访问 {b}", "hint": "可用 Bing 缓存查看"}
    cache_key = f"fetch:{url}"
    cached = fetch_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        import requests
        resp = requests.get(url, timeout=15, headers=_HEADERS, allow_redirects=True)
        resp.raise_for_status()
        try:
            ct = resp.content.decode(resp.encoding or "utf-8", errors="replace")
        except Exception:
            ct = resp.text
        if not ct:
            ct = resp.content.decode("utf-8", errors="replace")
        maxc = 15000
        result = {"success": True, "content": ct[:maxc], "url": resp.url,
                  "truncated": len(ct) > maxc, "length": len(ct)}
        fetch_cache.set(cache_key, result)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def _web_search(query: str, count: int = 5) -> dict:
    """使用插拔式 search engine 搜索（LRU 缓存，TTL=180s）"""
    cache_key = f"search:{query}:{count}"
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        from hedera.search.engine import search as _hedera_search
        result = _hedera_search(query, count)
        if result.get("success"):
            search_cache.set(cache_key, result)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


def _open_folder(path: str) -> dict:
    """在 Windows 资源管理器中打开文件夹"""
    try:
        import subprocess
        subprocess.Popen(["explorer", os.path.normpath(path)])
        return {"success": True, "message": f"已打开: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_process_list() -> dict:
    r = _exec_shell("tasklist /fo csv /nh")
    if r["success"]:
        lines = r["stdout"].strip().split("\n")
        ps = []
        for line in lines[:50]:
            p = [x.strip(' "') for x in line.split('","')]
            if len(p) >= 5:
                ps.append({"name": p[0], "pid": p[1], "session": p[2], "mem": p[4]})
        return {"success": True, "processes": ps}
    return {"success": False, "error": r["stderr"]}


# ─── 工具注册系统 ───────────

_TOOLS: dict[str, dict] = {}

def register_tool(name: str, desc: str, fn: Callable, params: dict = None):
    with _tools_lock:
        _TOOLS[name] = {"name": name, "description": desc, "function": fn,
                         "parameters": params or {"type": "object", "properties": {}, "required": []}}

def get_tool_descriptions() -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                               "parameters": t["parameters"]}}
            for t in _TOOLS.values()]

def call_tool(name: str, args: dict = None) -> dict:
    from hedera.core.logger import METRICS, Timer
    _timer = Timer()
    if name not in _TOOLS:
        METRICS.record_tool_call(name, success=False, latency=0.001)
        return {"success": False, "error": f"未知工具: {name}"}
    try:
        result = _TOOLS[name]["function"](**(args or {}))
        METRICS.record_tool_call(name, success=result.get("success", False), latency=_timer.elapsed())
        return result
    except Exception as e:
        METRICS.record_tool_call(name, success=False, latency=_timer.elapsed())
        return {"success": False, "error": str(e)}


# 注册工具
register_tool("exec_shell",
              "Run shell commands. Dangerous commands blocked, 60s timeout.",
              _exec_shell, {"type": "object", "properties": {"cmd": {"type": "string"},
                             "timeout": {"type": "integer", "default": 30}}, "required": ["cmd"]})
register_tool("read_file", "Read a text file.", _read_file,
              {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
register_tool("write_file", "Write a text file.", _write_file,
              {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
               "required": ["path", "content"]})
register_tool("list_dir", "List directory contents.", _list_dir,
              {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]})
register_tool("web_fetch", "Fetch web page content.", _web_fetch,
              {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]})
register_tool("web_search", "Search the internet.", _web_search,
              {"type": "object", "properties": {"query": {"type": "string"}, "count": {"type": "integer", "default": 5}},
               "required": ["query"]})
register_tool("open_folder", "Open a folder in Explorer.",
              _open_folder, {"type": "object", "properties": {"path": {"type": "string", "description": "文件夹路径"}},
                           "required": ["path"]})
def _cache_stats() -> dict:
    """查看缓存状态"""
    return {"success": True, "caches": {
        "search": search_cache.stats,
        "fetch": fetch_cache.stats,
        "file": file_cache.stats,
    }}


def _clear_cache(target: str = "all") -> dict:
    """清空缓存"""
    targets = {
        "search": search_cache,
        "fetch": fetch_cache,
        "file": file_cache,
    }
    if target == "all":
        for c in targets.values():
            c.clear()
        return {"success": True, "message": "所有缓存已清空"}
    if target in targets:
        targets[target].clear()
        return {"success": True, "message": f"{target} 缓存已清空"}
    return {"success": False, "error": f"未知缓存: {target}，可选: all/search/fetch/file"}


register_tool("get_process_list", "List system processes.", _get_process_list,
              {"type": "object", "properties": {}, "required": []})
register_tool("cache_stats", "View cache status.", _cache_stats,
              {"type": "object", "properties": {}, "required": []})
register_tool("send_file", "Send an existing file from disk to the user. Tell them the download URL in your response.",
              _send_existing_file,
              {"type": "object", "properties": {
                  "source_path": {"type": "string", "description": "服务器上的文件路径，如 C:\\Users\\Administrator\\Desktop\\xxx.py"},
                  "display_name": {"type": "string", "description": "显示给用户的文件名（可选）"},
               },
               "required": ["source_path"]})

register_tool("clear_cache", "Clear cache.", _clear_cache,
              {"type": "object", "properties": {"target": {"type": "string", "enum": ["all", "search", "fetch", "file"], "default": "all"}},
               "required": []})

register_tool("create_file", "Create a download file for the user (only for content >200 lines). Small code/output should be inlined in your response directly.",
              _create_download_file,
              {"type": "object", "properties": {
                  "filename": {"type": "string", "description": "文件名，如 code.py / report.md / config.yaml"},
                  "content": {"type": "string", "description": "文件内容"},
               },
               "required": ["filename", "content"]})

# ─── 图像生成 ───────────

_IMAGE_GEN_CONFIG = {}
_MODEL_ENDPOINT = ""


def set_image_gen_config(cfg: dict):
    """由 HTTP server 在启动时注入图像生成配置"""
    global _IMAGE_GEN_CONFIG
    _IMAGE_GEN_CONFIG = cfg


def set_model_endpoint(endpoint: str):
    """注入模型 API endpoint"""
    global _MODEL_ENDPOINT
    _MODEL_ENDPOINT = endpoint


def _generate_image(prompt: str, size: str = "") -> dict:
    """
    根据文本描述生成图像。
    配置在 config.yaml 的 image_gen 节设置。
    """
    cfg = _IMAGE_GEN_CONFIG or {}
    if not cfg.get("enabled", True):
        return {"success": False, "error": "图像生成未启用，请在 config.yaml 中配置 image_gen"}

    # endpoint: 优先用 image_gen.endpoint，否则用模型 endpoint（chat completions）
    raw_ep = cfg.get("endpoint", "") or _MODEL_ENDPOINT or "https://api.openai.com/v1/chat/completions"
    endpoint = raw_ep
    # 裸域名/base URL 没有 /chat/completions 路径时补上
    if not any(p in endpoint for p in ["/chat/completions", "/images/generations"]):
        endpoint = endpoint.rstrip("/") + "/v1/chat/completions"
    api_key = cfg.get("api_key", "") or os.environ.get(cfg.get("api_key_env", ""), "")
    model = cfg.get("model", "dall-e-3")
    n = cfg.get("n", 1)
    size = size or cfg.get("size", "1024x1024")

    if not api_key:
        return {"success": False, "error": "图像生成 API Key 未配置"}

    try:
        import requests
        # 构建备选端点列表：先试 chat/completions，再试 images/generations
        eps_to_try = [endpoint]
        if "/chat/completions" in endpoint:
            alt = endpoint.replace("/chat/completions", "/images/generations")
            if alt != endpoint:
                eps_to_try.append(alt)
        elif "/images/generations" in endpoint:
            alt = endpoint.replace("/images/generations", "/chat/completions")
            if alt != endpoint:
                eps_to_try.append(alt)

        last_err = ""
        resp_data = None
        for ep in eps_to_try:
            # 根据端点类型选择正确的 payload 格式
            is_img_endpoint = "/images/" in ep or "/v1/images/" in ep
            if is_img_endpoint:
                payload = {
                    "model": model,
                    "prompt": prompt,
                    "n": n,
                    "size": size,
                }
            else:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1024,
                }
            try:
                resp = requests.post(
                    ep,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                resp_data = resp.json()
                break
            except Exception as e:
                last_err = str(e)
                continue

        if resp_data is None:
            return {"success": False, "error": f"所有端点均失败: {last_err[:150]}"}
        data = resp_data

        images = []
        content = ""

        # 解析 chat completions 格式（choices[0].message.content）
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            pass

        if content:
            # 从 content 提取 HTTP 图片 URL 和 base64 data URI
            import re
            http_urls = re.findall(r'https?://[^\s"<>]+(?:\.png|\.jpg|\.jpeg|\.gif|\.webp)', content)
            for u in http_urls:
                images.append(u)
            # 提取 data URI（data:image/...;base64,...）
            data_uris = re.findall(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', content)
            for du in data_uris:
                images.append(du)

        # 其次解析 images/generations 格式
        if not images:
            for item in data.get("data", []):
                url = item.get("url", "")
                b64 = item.get("b64_json", "")
                if url:
                    images.append(url)
                elif b64:
                    images.append(f"data:image/png;base64,{b64}")

        if images:
            # 下载/解码图片到本地上传目录（绕过 Control UI 外域/跨域拦截）
            local_urls = []
            for img_url in images:
                try:
                    if img_url.startswith("data:"):
                        # base64 data URI → 解码存本地
                        import base64 as _b64
                        raw_b64 = img_url.split(",", 1)[1].strip()
                        # 去掉可能存在的换行和空白
                        raw_b64 = raw_b64.replace("\n", "").replace("\r", "").replace(" ", "")
                        # 补全 padding
                        raw_b64 += "=" * ((4 - len(raw_b64) % 4) % 4)
                        img_data = _b64.b64decode(raw_b64)
                        ext = ".png"
                        mtype = img_url.split(";")[0].split("/")[-1] if ";" in img_url else "png"
                        if mtype in ("jpeg", "jpg"): ext = ".jpg"
                        elif mtype == "gif": ext = ".gif"
                        elif mtype == "webp": ext = ".webp"
                    else:
                        import urllib.request
                        img_resp = urllib.request.urlopen(img_url, timeout=30)
                        img_data = img_resp.read()
                        ext = os.path.splitext(urllib.parse.urlparse(img_url).path)[1] or ".png"
                    fname = f"img_{uuid.uuid4().hex[:12]}{ext}"
                    save_dir = _uploads_dir if _uploads_dir else os.path.join(os.getcwd(), "uploads")
                    local_path = os.path.join(save_dir, "_common", fname)
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with open(local_path, "wb") as f:
                        f.write(img_data)
                    local_urls.append(f"/download/_common/{fname}")
                except Exception as e:
                    local_urls.append(img_url)  # 下载失败保留原始 URL

            md_images = [f"![{prompt[:30]}]({u})" for u in local_urls]
            return {
                "success": True,
                "images": local_urls,
                "markdown": "\n".join(md_images),
                "prompt": prompt,
                "model": model,
                "size": size,
                "count": len(images),
            }

        # 都没有图片 URL，返回 content 本身（模型可能只是描述了一张图）
        if content:
            return {"success": True, "images": [], "prompt": prompt, "model": model, "text": content}
        return {"success": False, "error": "API 返回了空的结果"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "图像生成请求超时（120s）"}
    except requests.exceptions.RequestException as e:
        detail = str(e)[:200]
        if hasattr(e, "response") and e.response is not None:
            try:
                detail = e.response.text[:200]
            except Exception:
                pass
        return {"success": False, "error": f"图像生成失败: {detail}"}
    except Exception as e:
        return {"success": False, "error": f"图像生成异常: {str(e)[:200]}"}


register_tool("generate_image",
              "Generate images from text description. Requires image_gen config in config.yaml. "
              "Returns image URLs in 'images' array and ready-to-use Markdown in 'markdown' field. "
              "CRITICAL: You MUST paste the 'markdown' content UNCHANGED into your response so the user can see the image. "
              "Your response should start with the markdown image.",
              
              _generate_image,
              {"type": "object", "properties": {
                  "prompt": {"type": "string", "description": "English prompt works best for most models"},
                  "size": {"type": "string", "description": "Image size, e.g. 1024x1024, 1792x1024 (default from config)", "default": ""},
               },
               "required": ["prompt"]})


ALL_TOOL_NAMES = list(_TOOLS.keys())


def format_tool_results(results: list[dict]) -> str:
    parts = []
    for r in results:
        name = r.get("name", "?")
        res = r.get("result", {})
        if res.get("success"):
            parts.append(f"【{name}】成功")
            if "content" in res:
                c = res["content"]
                if res.get("truncated"):
                    c += "\n（截断，仅显示前15000字符）"
                parts.append(c)
            elif "stdout" in res and res["stdout"].strip():
                parts.append(res["stdout"])
            elif "results" in res:
                items = res["results"]
                note = res.get("note", "")
                if note:
                    parts.append(f"⚠️ {note}")
                parts.append(f"共{len(items)}条（来源: {res.get('source','?')}）")
                for i, it in enumerate(items, 1):
                    s = it.get("snippet", "")
                    parts.append(f"{i}. {it.get('title','')}{' — '+s[:200] if s else ''}\n   {it.get('url','')}")
            elif "items" in res:
                for it in res["items"]:
                    parts.append(f"  {'📁' if it['type']=='dir' else '📄'} {it['name']} ({it['size']}B)")
            elif "processes" in res:
                for p in res["processes"]:
                    parts.append(f"  {p['name']} (PID:{p['pid']}, {p['mem']})")
            else:
                parts.append(str(res))
        else:
            e = res.get("error", "未知错误")
            h = res.get("hint", "")
            d = res.get("detail", "")
            m = f"【{name}】失败: {e}"
            if d:
                m += f" ({d})"
            if h:
                m += f"\n提示: {h}"
            parts.append(m)
    return "\n".join(parts)
