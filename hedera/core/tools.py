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
_workspace_dir: str = ""

def set_uploads_dir(path: str):
    """设置上传目录（供 HTTP handler 调用）"""
    global _uploads_dir
    _uploads_dir = path

def set_workspace_dir(path: str):
    """设置工作区目录（供 HTTP handler 调用）"""
    global _workspace_dir
    _workspace_dir = path
    os.makedirs(path, exist_ok=True)
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


def _create_download_file(filename: str, content: str, server_url: str = "") -> dict:
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
        # 如果没有指定服务器URL，使用相对路径
        if server_url:
            full_url = f"{server_url.rstrip('/')}{url}"
        else:
            full_url = url
        return {
            "success": True,
            "file": safe_name,
            "size": len(content.encode("utf-8")),
            "url": full_url,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}



def _exec_shell(cmd: str, timeout: int = 120) -> dict:
    # 输入校验
    validation = validate_shell_command(cmd, timeout)
    if validation is not None:
        return validation
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                timeout=timeout, encoding="utf-8", errors="replace",
                                cwd=_workspace_dir if _workspace_dir else None)
        return {
            "stdout": truncate_output(result.stdout),
            "stderr": truncate_output(result.stderr),
            "returncode": result.returncode,
            "success": result.returncode == 0,
            "cwd": _workspace_dir or os.getcwd(),
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"超时（{timeout}s）", "returncode": -1, "success": False}
    except Exception as e:
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
    """原子写入：先写 .tmp 再 rename，崩溃不影响原文件。
    相对路径默认写入工作区目录。"""
    # 相对路径 → 工作区路径
    if not os.path.isabs(path) and _workspace_dir:
        path = os.path.join(_workspace_dir, path)
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


def _read_file(path: str, offset: int = 0, limit: int = 0) -> dict:
    """读取文本文件。offset: 起始行号(从1开始), limit: 读取行数(0=全部)"""
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    # 缓存键包含文件 mtime → 文件修改后自动失效
    try:
        mtime = os.path.getmtime(safe_path)
    except Exception:
        mtime = 0
    cache_key = f"file:{safe_path}:{mtime}:{offset}:{limit}"
    cached = file_cache.get(cache_key)
    if cached is not None:
        return cached
    with _file_io_lock:
        try:
            with open(safe_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            total = len(lines)
            if offset > 0:
                lines = lines[offset - 1:]
            if limit > 0:
                lines = lines[:limit]
            # 全量读取时限制为 200 行，超出时提示分段
            if not offset and not limit and total > 200:
                lines = lines[:200]
                content = "".join(lines)
                content += f"\n...（文件共 {total} 行，已显示前 200 行。用 offset=201 继续读取，或用 offset+limit 指定范围）"
            else:
                content = "".join(lines)
            result = {"success": True, "content": content, "total_lines": total}
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
                full = os.path.join(safe_path, item)
                items.append({"name": item,
                              "type": "dir" if os.path.isdir(full) else "file",
                              "size": os.path.getsize(full) if not os.path.isdir(full) else 0})
            return {"success": True, "path": safe_path, "items": items}
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


def _grep_files(pattern: str, path: str = ".", include: str = "", max_results: int = 50, context: int = 0) -> dict:
    """Recursively search file contents. Like grep -rn.
    context: 匹配行前后各显示N行（默认0=只显示匹配行）"""
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    try:
        results = []
        count = 0
        regex = re.compile(pattern, re.IGNORECASE)
        for root, dirs, files in os.walk(safe_path):
            # Skip common non-useful directories
            dirs[:] = [d for d in dirs if d not in (
                '.git', 'node_modules', '__pycache__', '.venv', 'venv',
                'env', '.env', '.idea', '.vscode', 'dist', 'build',
                '.tox', '.eggs', '*.egg-info', 'hedera.db')]
            for fname in files:
                if include:
                    ext = include if include.startswith('.') else f'.{include}'
                    if not fname.endswith(ext):
                        continue
                fpath = os.path.join(root, fname)
                # Skip binary files
                if os.path.getsize(fpath) > 1_000_000:
                    continue
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        all_lines = f.readlines()
                    matched_lines = []
                    for i, line in enumerate(all_lines):
                        if regex.search(line):
                            matched_lines.append(i)
                    if not matched_lines:
                        continue
                    rel = os.path.relpath(fpath, safe_path)
                    for line_idx in matched_lines:
                        entry = {"file": rel, "line": line_idx + 1, "text": all_lines[line_idx].rstrip()[:200]}
                        if context > 0:
                            start = max(0, line_idx - context)
                            end = min(len(all_lines), line_idx + context + 1)
                            ctx_lines = []
                            for ci in range(start, end):
                                prefix = ">>>" if ci == line_idx else "   "
                                ctx_lines.append(f"{prefix} {ci+1}: {all_lines[ci].rstrip()[:120]}")
                            entry["context"] = "\n".join(ctx_lines)
                        results.append(entry)
                        count += 1
                        if count >= max_results:
                            return {"success": True, "results": results,
                                    "truncated": True, "total_shown": count}
                except Exception:
                    continue
        return {"success": True, "results": results, "truncated": False, "total_shown": count}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _edit_file(path: str, old_text: str, new_text: str, occurrence: int = 1) -> dict:
    """Precise text replacement in a file.
    Finds exact old_text match and replaces with new_text.
    occurrence: 第几个匹配项（从1开始，默认1=第一个）。
    Use read_file first to see the current content."""
    import difflib
    safe_path = validate_write_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    with _file_io_lock:
        try:
            with open(safe_path, 'r', encoding='utf-8') as f:
                content = f.read()
            # 统一换行符处理
            work_content = content.replace('\r\n', '\n')
            work_old = old_text.replace('\r\n', '\n')
            work_new = new_text.replace('\r\n', '\n')
            # 找到第 occurrence 个匹配
            idx = -1
            search_from = 0
            for _ in range(occurrence):
                idx = work_content.find(work_old, search_from)
                if idx == -1:
                    break
                search_from = idx + len(work_old)
            if idx == -1:
                return {"success": False, "error": f"old_text 在文件中未找到第 {occurrence} 个匹配，用 read_file 确认当前内容"}
            # 替换
            new_content = work_content[:idx] + work_new + work_content[idx+len(work_old):]
            # 如果原文件是 \r\n，还原回去
            if '\r\n' in content and '\r\n' not in new_content:
                new_content = new_content.replace('\n', '\r\n')
            # 生成 diff（截取变更区域前后各3行）
            old_lines = work_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
            diff_text = "".join(diff)[:2000]  # 限制 diff 长度
            # Atomic write
            tmp_path = safe_path + '.hedera_tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, safe_path)
            return {"success": True, "path": safe_path, "replacements": 1, "diff": diff_text}
        except Exception as e:
            return {"success": False, "error": str(e)}


def _git_status(path: str = ".") -> dict:
    """Get git status, branch, recent commits, and project structure."""
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    result = {}
    try:
        # Git branch
        r = subprocess.run(['git', 'branch', '--show-current'],
                           capture_output=True, text=True, cwd=safe_path, timeout=5)
        result['branch'] = r.stdout.strip() if r.returncode == 0 else ''
        # Git status (short)
        r = subprocess.run(['git', 'status', '--short'],
                           capture_output=True, text=True, cwd=safe_path, timeout=5)
        result['status'] = r.stdout.strip()[:2000] if r.returncode == 0 else ''
        # Recent commits
        r = subprocess.run(['git', 'log', '--oneline', '-5'],
                           capture_output=True, text=True, cwd=safe_path, timeout=5)
        result['recent_commits'] = r.stdout.strip()[:1000] if r.returncode == 0 else ''
        # Diff (unstaged)
        r = subprocess.run(['git', 'diff', '--stat'],
                           capture_output=True, text=True, cwd=safe_path, timeout=5)
        result['diff_stat'] = r.stdout.strip()[:1000] if r.returncode == 0 else ''
    except Exception as e:
        result['git_error'] = str(e)
    # Project file tree (top 2 levels)
    try:
        tree_lines = []
        skip = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'env',
                '.env', '.idea', 'dist', 'build', '.tox', '.eggs'}
        for root, dirs, files in os.walk(safe_path):
            depth = root.replace(safe_path, '').count(os.sep)
            if depth > 1:
                continue
            dirs[:] = [d for d in dirs if d not in skip]
            indent = '  ' * depth
            basename = os.path.basename(root)
            if depth > 0:
                tree_lines.append(f"{indent}{basename}/")
            for f in sorted(files)[:20]:
                tree_lines.append(f"{indent}  {f}")
        result['file_tree'] = '\n'.join(tree_lines[:80])
    except Exception as e:
        result['tree_error'] = str(e)
    return {"success": True, **result}


def _find_definition(name: str, path: str = ".", include: str = "") -> dict:
    """Find where a function, class, or variable is defined.
    Searches for common definition patterns like 'def name', 'class name', 'name =', etc."""
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    try:
        # 根据文件类型构建搜索模式
        patterns = [
            rf"^\s*(?:async\s+)?def\s+{re.escape(name)}\s*\(",  # Python function
            rf"^\s*class\s+{re.escape(name)}\s*[\(:]",  # Python class
            rf"^\s*{re.escape(name)}\s*=",  # Python variable assignment
            rf"^\s*(?:export\s+)?(?:function|const|let|var)\s+{re.escape(name)}\b",  # JS function/variable
            rf"^\s*(?:export\s+)?class\s+{re.escape(name)}\b",  # JS class
            rf"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)?{re.escape(name)}\s*\(",  # Java/C# method
        ]
        combined = "|".join(patterns)
        results = []
        for root, dirs, files in os.walk(safe_path):
            dirs[:] = [d for d in dirs if d not in (
                '.git', 'node_modules', '__pycache__', '.venv', 'venv',
                'env', '.env', '.idea', '.vscode', 'dist', 'build')]
            for fname in files:
                if include:
                    ext = include if include.startswith('.') else f'.{include}'
                    if not fname.endswith(ext):
                        continue
                fpath = os.path.join(root, fname)
                if os.path.getsize(fpath) > 1_000_000:
                    continue
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f, 1):
                            if re.search(combined, line):
                                rel = os.path.relpath(fpath, safe_path)
                                results.append({"file": rel, "line": i, "text": line.rstrip()[:200]})
                                if len(results) >= 20:
                                    return {"success": True, "results": results, "truncated": True}
                except Exception:
                    continue
        return {"success": True, "results": results, "truncated": False}
    except Exception as e:
        return {"success": False, "error": str(e)}


# 注册工具
register_tool("exec_shell",
              "Execute shell commands. Runs in workspace directory by default. "
              "Use for running code, installing packages, git operations. "
              "Write code to files first with write_file, then execute. "
              "Default 120s timeout, max 600s. Returns stdout, stderr, returncode.",
              _exec_shell, {"type": "object", "properties": {"cmd": {"type": "string"},
                             "timeout": {"type": "integer", "default": 120}}, "required": ["cmd"]})
register_tool("read_file", "Read a text file. Can read any path. Large files auto-truncated; use offset+limit to read in chunks.", _read_file,
              {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer", "default": 0, "description": "Start line (1-based)"}, "limit": {"type": "integer", "default": 0, "description": "Max lines to read (0=all)"}}, "required": ["path"]})
register_tool("write_file", "Write a text file. Defaults to workspace directory if path is relative.", _write_file,
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
register_tool("grep_files",
              "Search file contents recursively. Like grep -rn. "
              "Use this to find code, functions, variables across the project. "
              "Returns file paths, line numbers, and matching text. "
              "Filter by file extension with 'include' param (e.g. '.py', '.js'). "
              "Use context=2 to see surrounding lines for better understanding.",
              _grep_files, {"type": "object", "properties": {
                  "pattern": {"type": "string", "description": "Regex pattern to search for"},
                  "path": {"type": "string", "description": "Directory to search in (default: current dir)", "default": "."},
                  "include": {"type": "string", "description": "File extension filter, e.g. '.py'", "default": ""},
                  "max_results": {"type": "integer", "description": "Max results to return", "default": 50},
                  "context": {"type": "integer", "description": "Show N lines before/after each match (default 0)", "default": 0}},
              "required": ["pattern"]})
register_tool("find_definition",
              "Find where a function, class, or variable is defined. "
              "Searches for 'def name', 'class name', 'name =' patterns across the project. "
              "Use this instead of grep_files when looking for a specific symbol's definition.",
              _find_definition, {"type": "object", "properties": {
                  "name": {"type": "string", "description": "Function, class, or variable name to find"},
                  "path": {"type": "string", "description": "Directory to search in", "default": "."},
                  "include": {"type": "string", "description": "File extension filter", "default": ""}},
              "required": ["name"]})
register_tool("edit_file",
              "Precise text replacement in a file. Finds exact old_text and replaces with new_text. "
              "MUST use read_file first to see current content before editing. "
              "old_text must match exactly (including whitespace and indentation). "
              "Use occurrence parameter when the same text appears multiple times. "
              "For new files or full rewrites, use write_file instead.",
              _edit_file, {"type": "object", "properties": {
                  "path": {"type": "string", "description": "File path"},
                  "old_text": {"type": "string", "description": "Exact text to find and replace (must match exactly)"},
                  "new_text": {"type": "string", "description": "Replacement text"},
                  "occurrence": {"type": "integer", "description": "Which occurrence to replace (1-based, default 1)", "default": 1}},
              "required": ["path", "old_text", "new_text"]})
register_tool("git_status",
              "Get project context: git branch, status, recent commits, diff stats, and file tree. "
              "Call this first when starting work on a codebase to understand the project.",
              _git_status, {"type": "object", "properties": {
                  "path": {"type": "string", "description": "Project root directory", "default": "."}},
              "required": []})

# ─── 代码增强工具 ───────────

def _run_tests(path: str = ".", framework: str = "") -> dict:
    """自动检测并运行项目的测试框架"""
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}

    # 自动检测测试框架
    detected = framework
    if not detected:
        # 检查常见测试配置文件
        test_files = {
            "pytest": ["pytest.ini", "pyproject.toml", "setup.cfg"],
            "unittest": [],  # Python 内置
            "jest": ["jest.config.js", "jest.config.ts", "package.json"],
            "mocha": [".mocharc.yml", ".mocharc.js"],
            "vitest": ["vitest.config.ts", "vitest.config.js"],
        }
        for fw, files in test_files.items():
            for f in files:
                if os.path.exists(os.path.join(safe_path, f)):
                    detected = fw
                    break
            if detected:
                break

        # 检查 Python 测试文件
        if not detected:
            for root, dirs, files in os.walk(safe_path):
                for f in files:
                    if f.startswith("test_") and f.endswith(".py"):
                        detected = "pytest"
                        break
                if detected:
                    break

        # 检查 JS 测试文件
        if not detected:
            for root, dirs, files in os.walk(safe_path):
                for f in files:
                    if f.endswith(".test.js") or f.endswith(".test.ts") or f.endswith(".spec.js"):
                        detected = "jest"
                        break
                if detected:
                    break

    if not detected:
        return {"success": False, "error": "未检测到测试框架，请指定 framework 参数"}

    # 运行测试
    test_cmds = {
        "pytest": f"{sys.executable} -m pytest -v --tb=short",
        "unittest": f"{sys.executable} -m unittest discover -v",
        "jest": "npx jest --verbose",
        "mocha": "npx mocha --reporter spec",
        "vitest": "npx vitest run",
    }

    cmd = test_cmds.get(detected)
    if not cmd:
        return {"success": False, "error": f"不支持的测试框架: {detected}"}

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                timeout=120, encoding="utf-8", errors="replace",
                                cwd=safe_path)
        return {
            "success": result.returncode == 0,
            "framework": detected,
            "stdout": truncate_output(result.stdout),
            "stderr": truncate_output(result.stderr),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "测试超时（120s）"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _edit_file_by_line(path: str, start_line: int, end_line: int, new_content: str) -> dict:
    """按行号范围精确编辑文件（比文本匹配更可靠）
    start_line: 起始行号（从1开始）
    end_line: 结束行号（包含）
    new_content: 替换内容"""
    safe_path = validate_write_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    with _file_io_lock:
        try:
            with open(safe_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            total = len(lines)
            if start_line < 1 or start_line > total:
                return {"success": False, "error": f"起始行 {start_line} 超出范围 (1-{total})"}
            if end_line < start_line or end_line > total:
                return {"success": False, "error": f"结束行 {end_line} 超出范围 ({start_line}-{total})"}

            # 构建新内容
            new_lines = (new_content + '\n').splitlines(True)
            new_file = lines[:start_line-1] + new_lines + lines[end_line:]

            # 原子写入
            import difflib
            old_text = ''.join(lines[start_line-1:end_line])
            diff = list(difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3
            ))

            tmp_path = safe_path + '.hedera_tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.writelines(new_file)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, safe_path)

            return {
                "success": True,
                "path": safe_path,
                "lines_replaced": end_line - start_line + 1,
                "new_lines": len(new_lines),
                "diff": ''.join(diff)[:2000],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def _find_references(name: str, path: str = ".", include: str = "") -> dict:
    """查找函数、变量、类的所有引用位置（比 grep_files 更精准）"""
    safe_path = validate_read_path(path)
    if safe_path is None:
        return {"success": False, "error": f"路径被阻止: {path[:60]}"}
    try:
        # 构建精确匹配模式（避免部分匹配）
        patterns = [
            rf'\b{re.escape(name)}\b',  # 单词边界匹配
        ]
        results = []
        for root, dirs, files in os.walk(safe_path):
            dirs[:] = [d for d in dirs if d not in (
                '.git', 'node_modules', '__pycache__', '.venv', 'venv',
                'env', '.env', '.idea', '.vscode', 'dist', 'build')]
            for fname in files:
                if include:
                    ext = include if include.startswith('.') else f'.{include}'
                    if not fname.endswith(ext):
                        continue
                fpath = os.path.join(root, fname)
                if os.path.getsize(fpath) > 1_000_000:
                    continue
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f, 1):
                            if re.search(patterns[0], line):
                                rel = os.path.relpath(fpath, safe_path)
                                results.append({"file": rel, "line": i, "text": line.rstrip()[:200]})
                                if len(results) >= 50:
                                    return {"success": True, "results": results, "truncated": True}
                except Exception:
                    continue
        return {"success": True, "results": results, "truncated": False}
    except Exception as e:
        return {"success": False, "error": str(e)}


register_tool("run_tests",
              "Auto-detect and run project test framework (pytest, jest, mocha, etc). "
              "Returns test results with pass/fail counts.",
              _run_tests, {"type": "object", "properties": {
                  "path": {"type": "string", "description": "Project directory", "default": "."},
                  "framework": {"type": "string", "description": "Force framework (pytest/jest/mocha)", "default": ""}},
              "required": []})

register_tool("edit_file_by_line",
              "Edit file by line numbers (more reliable than text matching for large edits). "
              "Specify start_line and end_line to replace that range with new_content.",
              _edit_file_by_line, {"type": "object", "properties": {
                  "path": {"type": "string", "description": "File path"},
                  "start_line": {"type": "integer", "description": "Start line (1-based)"},
                  "end_line": {"type": "integer", "description": "End line (inclusive)"},
                  "new_content": {"type": "string", "description": "Replacement content"}},
              "required": ["path", "start_line", "end_line", "new_content"]})

register_tool("find_references",
              "Find all usages/references of a function, variable, or class name. "
              "More precise than grep_files for code symbols.",
              _find_references, {"type": "object", "properties": {
                  "name": {"type": "string", "description": "Symbol name to find"},
                  "path": {"type": "string", "description": "Directory to search", "default": "."},
                  "include": {"type": "string", "description": "File extension filter", "default": ""}},
              "required": ["name"]})

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



def _run_python(code: str, timeout: int = 120) -> dict:
    """Run Python code in a temp file with proper error handling.
    Runs in workspace directory by default."""
    import tempfile
    # 校验代码安全性（阻止危险模块和系统调用）
    code_lower = code.lower()
    for blocked in ["os.system", "subprocess.call", "subprocess.run", "subprocess.Popen",
                    "shutil.rmtree", "os.remove", "os.unlink", "eval(", "exec("]:
        if blocked in code_lower:
            return {"success": False, "error": f"安全限制: 代码包含 '{blocked}'，已阻止执行"}
    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
            dir=_workspace_dir if _workspace_dir else None
        )
        tmp.write(code)
        tmp.close()
        result = subprocess.run(
            [sys.executable or "python", tmp.name],
            capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            cwd=_workspace_dir if _workspace_dir else None
        )
        return {
            "stdout": truncate_output(result.stdout),
            "stderr": truncate_output(result.stderr),
            "returncode": result.returncode,
            "success": result.returncode == 0,
            "cwd": _workspace_dir or os.getcwd(),
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"超时（{timeout}s）", "returncode": -1, "success": False}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "success": False}
    finally:
        if tmp:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

register_tool("run_python",
              "Run Python code directly. Pass the full code as a string. "
              "Use this instead of exec_shell for Python tasks. "
              "Stdout and stderr are captured. Default 120s timeout.",
              _run_python, {"type": "object", "properties": {
                  "code": {"type": "string", "description": "Python code to execute"},
                  "timeout": {"type": "integer", "default": 120}}, "required": ["code"]})

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
              "Optionally accepts an 'image' parameter with a reference image URL for image-to-image generation. "
              "CRITICAL: You MUST paste the 'markdown' content UNCHANGED into your response so the user can see the image. "
              "Your response should start with the markdown image.",
              _generate_image,
              {"type": "object", "properties": {
                  "prompt": {"type": "string", "description": "English prompt works best for most models"},
                  "size": {"type": "string", "description": "Image size, e.g. 1024x1024, 1792x1024 (default from config)", "default": ""},
                  "image": {"type": "string", "description": "Reference image URL (optional, for image-to-image)", "default": ""},
               },
               "required": ["prompt"]})

# ─── 热梗学习 ───────────

def _learn_meme(meme_text: str, trigger_words: list[str]) -> dict:
    """学习新梗并更新词库"""
    try:
        from hedera.core.meme_learner import learn_meme
        success = learn_meme(meme_text, trigger_words)
        return {"success": success, "message": f"已学习热梗: {meme_text[:50]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _get_learned_memes() -> dict:
    """获取已学习的热梗列表"""
    try:
        from hedera.core.meme_learner import get_learned_memes
        memes = get_learned_memes()
        return {"success": True, "count": len(memes), "memes": memes[:20]}
    except Exception as e:
        return {"success": False, "error": str(e)}


register_tool("learn_meme",
              "Learn a new internet meme and add it to the vocabulary. "
              "Provide the meme description and trigger words.",
              _learn_meme,
              {"type": "object", "properties": {
                  "meme_text": {"type": "string", "description": "Description of the meme"},
                  "trigger_words": {"type": "array", "items": {"type": "string"}, "description": "List of trigger words"},
               },
               "required": ["meme_text", "trigger_words"]})

register_tool("get_learned_memes",
              "Get list of learned internet memes.",
              _get_learned_memes,
              {"type": "object", "properties": {}, "required": []})

# ─── 进度汇报 ───────────

def _report_progress(text: str) -> dict:
    """向用户汇报中间进度，不中断当前任务"""
    return {"success": True, "reported": True, "message": text}

register_tool("report_progress",
              "Report intermediate progress to the user during long tasks. "
              "Use this to keep the user informed about what you're doing. "
              "The message is shown immediately without interrupting the workflow.",
              _report_progress,
              {"type": "object", "properties": {
                  "text": {"type": "string", "description": "Progress message to show the user"}},
               "required": ["text"]})

# ─── 浏览器自动化（批量模式）───────────

def _browser_run(steps: list) -> dict:
    from hedera.core.browser import browser_run
    return browser_run(steps)

def _browser_script(code: str) -> dict:
    from hedera.core.browser import browser_script
    return browser_script(code)

def _browser_cdp(method: str, params: dict = None) -> dict:
    from hedera.core.browser import browser_cdp
    return browser_cdp(method, params)

def _browser_close() -> dict:
    from hedera.core.browser import browser_close
    return browser_close()

register_tool("browser_run",
              "Execute browser operations in one call. Actions: "
              "navigate(url), see(screenshot+interactive elements), type(selector,text,enter), click(selector), "
              "wait(ms), screenshot, content(max_length), scroll(direction,amount), select(selector,value), eval(code), back, forward, reload. "
              "'see' returns a screenshot + list of clickable/typeable elements (no CSS needed). "
              "Selectors can be placeholder text, name, aria-label, or button text instead of CSS.",
              _browser_run,
              {"type": "object", "properties": {
                  "steps": {"type": "array", "description": "List of operations. Each has 'action' field + params.",
                            "items": {"type": "object", "properties": {
                                "action": {"type": "string", "description": "Operation type"}
                            }, "required": ["action"]}}
               },
               "required": ["steps"]})

register_tool("browser_script",
              "Execute JavaScript directly in the browser page. Fastest way to interact with DOM. "
              "Can read/write page content, click elements, fill forms, all in one call. "
              "Example: \"document.querySelector('#search').value='test'; document.querySelector('button').click()\"",
              _browser_script,
              {"type": "object", "properties": {
                  "code": {"type": "string", "description": "JavaScript code to execute in browser context"}},
               "required": ["code"]})

register_tool("browser_cdp",
              "Send raw CDP (Chrome DevTools Protocol) command. Low-level browser control. "
              "Examples: Network.enable, Runtime.evaluate, Page.captureScreenshot",
              _browser_cdp,
              {"type": "object", "properties": {
                  "method": {"type": "string", "description": "CDP method name"},
                  "params": {"type": "object", "description": "CDP method parameters", "default": {}}},
               "required": ["method"]})

register_tool("browser_close",
              "Close the browser and free resources.",
              _browser_close,
              {"type": "object", "properties": {}, "required": []})


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
