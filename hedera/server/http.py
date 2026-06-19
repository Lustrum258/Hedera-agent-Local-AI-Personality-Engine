"""
Hedera HTTP 服务
基于 Python 内置 http.server，零依赖 Web 服务。
"""

import os
import sys
import json
import base64
import threading
import time
import mimetypes
import time
import uuid
import urllib.request
import re as _re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Callable

from hedera.config import ConfigManager, load_config, get_data_dir
from hedera.docs_zh_cn import DOCS_MARKDOWN as DOCS_MARKDOWN_ZH
from hedera.docs_en_us import DOCS_MARKDOWN as DOCS_MARKDOWN_EN
from hedera.core.router import (
    process_message, process_message_stream, reset_state, shutdown as router_shutdown,
    get_reflection_log, get_reflection_details, get_experience_log,
    _do_reflection,
)
from hedera.core.memory_store import MemoryStore
from hedera.core.experience import distill_experience_once
from hedera.core.tools import ALL_TOOL_NAMES, get_tool_descriptions
from hedera.core.cache import search_cache, fetch_cache, file_cache
from hedera.training.signal import SignalManager


# ─── 预设文件辅助 ───
def _presets_path(data_dir: str) -> str:
    return os.path.join(data_dir, "model_presets.json")

def _load_presets_file(data_dir: str) -> dict:
    p = _presets_path(data_dir)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"presets": {"llm": [], "img": [], "tts": []}}

def _save_presets_file(data_dir: str, data: dict):
    p = _presets_path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _generate_title_async(user_msg: str, assistant_msg: str, session_id: str, data_dir: str, config: dict):
    """异步调用 LLM 生成会话标题"""
    def _run():
        try:
            from hedera.core.api import _call_api
            from hedera.core.memory_store import MemoryStore

            user_short = user_msg[:300].replace("\n", " ").strip()
            resp_short = assistant_msg[:300].replace("\n", " ").strip()

            messages = [
                {"role": "system", "content": "你是一个会话标题生成器。根据用户的问题和AI的回答，生成一个简短的中文标题（15字以内）。只输出标题，不要任何标点符号或引号。"},
                {"role": "user", "content": f"用户：{user_short}\n助手：{resp_short}"},
            ]

            result = _call_api(messages, config, temperature_override=0.3, max_tokens_override=30)
            title = (result.get("content") or "").strip().strip('"').strip("'").strip("「」")

            if title and len(title) >= 2:
                store = MemoryStore(data_dir, session_id="_title")
                store.update_session_title(session_id, title)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


class HederaHandler(BaseHTTPRequestHandler):
    config = {}
    data_dir = ""

    def _get_allowed_origin(self):
        """获取允许的 CORS origin"""
        # 允许本地访问
        origin = self.headers.get("Origin", "")
        if origin:
            # 检查是否是本地访问
            allowed_origins = [
                "http://localhost",
                "http://127.0.0.1",
                "http://0.0.0.0",
                "https://localhost",
                "https://127.0.0.1",
            ]
            for allowed in allowed_origins:
                if origin.startswith(allowed):
                    return origin
        # 如果是本地访问但没有 Origin 头，允许
        return "http://localhost"

    def handle_error(self, request, client_address):
        """覆盖默认行为：连接类异常静默，其他异常仅打一行摘要"""
        cls, exc, _ = sys.exc_info()
        if cls in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return  # 客户端断连，静默
        if cls.__name__ == "SSLError":
            return  # 扫描器用 HTTPS 连纯 HTTP 端口，静默
        print(f"[Hedera] {client_address[0]} - {cls.__name__}: {exc}", file=sys.stderr)

    def _refresh_config(self):
        """从 ConfigManager 拉取最新配置（自动检测文件变更）"""
        global _config_manager
        if _config_manager is not None:
            new_cfg = _config_manager.get()
            if new_cfg != self.config:
                old_pwd = self.config.get("server", {}).get("password", "")
                self.config = new_cfg
                # 每次刷新重新注入 API Key
                from hedera.server.http import _setup_api_keys
                try:
                    _setup_api_keys(self.config)
                except Exception:
                    pass
                # 热重载图像生成配置
                from hedera.core.tools import set_image_gen_config, set_model_endpoint
                try:
                    set_image_gen_config(self.config.get("image_gen", {}))
                    set_model_endpoint(self.config.get("model", {}).get("endpoint", ""))
                except Exception:
                    pass
                new_pwd = self.config.get("server", {}).get("password", "")
                from hedera.core.logger import info as _li
                _li("Config hot-reloaded", password_changed=bool(old_pwd and old_pwd != new_pwd))

    def _get_password(self):
        return self.config.get("server", {}).get("password", "")

    def _check_auth(self):
        pwd = self._get_password()
        if not pwd:
            return True
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        token = auth[7:]

        import hmac
        if hmac.compare_digest(token, pwd):
            return True

        if hasattr(self.__class__, '_active_tokens'):
            expiry = self.__class__._active_tokens.get(token)
            if expiry and time.time() < expiry:
                return True
            if expiry:
                del self.__class__._active_tokens[token]
        return False

    def _require_auth(self):
        if not self._check_auth():
            self._send_json({"error": "未授权"}, 401)
            return False
        return True

    def _dispatch_plugin_route(self, method: str):
        """将当前请求分发给插件路由"""
        pm = getattr(self, "plugin_manager", None)
        if not pm:
            return None

        # 解析 body（支持 multipart）
        body = None
        file_data = None
        file_name = None
        if method in ("POST", "PUT", "PATCH"):
            ctype = self.headers.get("Content-Type", "")
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw = bytearray()
                remaining = content_length
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 65536))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    remaining -= len(chunk)
                body = bytes(raw)

                # multipart: 提取文件
                if "multipart/form-data" in ctype:
                    m = _re.search(r"boundary=(.+)", ctype)
                    if m:
                        boundary = m.group(1).strip('"').strip("'")
                        sep = b"--" + boundary.encode()
                        parts = body.split(sep)
                        for part in parts:
                            if b"Content-Disposition" not in part:
                                continue
                            idx = part.find(b"\r\n\r\n")
                            if idx >= 0:
                                hdr_end = idx + 4
                            else:
                                idx = part.find(b"\n\n")
                                if idx < 0:
                                    continue
                                hdr_end = idx + 2
                            hdr_raw = part[:idx].decode("utf-8", errors="replace")
                            content = part[hdr_end:]
                            if content.endswith(b"\r\n"):
                                content = content[:-2]
                            if content.endswith(b"\n"):
                                content = content[:-1]
                            if 'name="file"' in hdr_raw:
                                fn_m = _re.search(r'filename="([^"]*)"', hdr_raw)
                                if fn_m:
                                    file_name = fn_m.group(1)
                                file_data = content

        headers = {k: v for k, v in self.headers.items()}
        result = pm.dispatch_http(
            method=method,
            path=self.path,
            headers=headers,
            body=body,
            file_data=file_data,
            file_name=file_name,
        )
        if result is None:
            return None

        # 解析返回值
        if len(result) == 3:
            data, code, content_type = result
            if isinstance(data, (bytes, bytearray)):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
                self.end_headers()
                self.wfile.write(data)
            elif isinstance(data, str):
                encoded = data.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
                self.end_headers()
                self.wfile.write(encoded)
            else:
                self._send_json(data, code)
        elif len(result) == 2:
            data, code = result
            if isinstance(data, (bytes, bytearray)):
                self.send_response(code)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
                self.end_headers()
                self.wfile.write(data)
            elif isinstance(data, str):
                encoded = data.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
                self.end_headers()
                self.wfile.write(encoded)
            else:
                self._send_json(data, code)
        return True

    def do_POST(self):
        from hedera.core.logger import METRICS
        METRICS.record_request()
        self._refresh_config()
        path = self.path.split("?")[0].rstrip("/")
        if path == "/login":
            return self._handle_login()
        if path == "/config/reload":
            if not self._require_auth():
                return
            return self._handle_config_reload()
        if not self._require_auth():
            return
        if path == "/chat":
            return self._handle_chat()
        elif path == "/webhook":
            return self._handle_webhook()
        elif path == "/tools":
            return self._handle_tools()
        elif path == "/config":
            return self._handle_post_config()
        elif path == "/api/presets":
            return self._handle_save_preset()
        elif path == "/api/presets/apply":
            return self._handle_apply_preset()
        elif path == "/sessions":
            return self._handle_create_session()
        elif path == "/sessions/clear_all":
            return self._handle_clear_all_sessions()
        elif path == "/api/distill":
            return self._handle_distill()
        elif path == "/api/training/pulse":
            return self._handle_training_pulse()
        elif path == "/test_conn":
            return self._handle_test_conn()
        elif path == "/api/tts":
            return self._handle_tts()
        elif path == "/api/profiles/create":
            return self._handle_create_profile()
        elif path == "/upload":
            return self._handle_upload()
        elif path == "/api/keys/set":
            return self._handle_set_api_key()
        elif path == "/api/keys/delete":
            return self._handle_delete_api_key()
        elif path == "/api/keys/migrate":
            return self._handle_migrate_keys()
        else:
            # 尝试插件路由分发
            result = self._dispatch_plugin_route("POST")
            if result is not None:
                return
            self._send_error(404)

    def do_DELETE(self):
        if not self._require_auth():
            return
        parsed = _re.match(r"^/sessions/([^/]+)$", self.path.rstrip("/"))
        if parsed:
            return self._handle_delete_session(parsed.group(1))
        parsed = _re.match(r"^/api/presets/([^/]+)$", self.path.rstrip("/"))
        if parsed:
            return self._handle_delete_preset(parsed.group(1))
        parsed = _re.match(r"^/api/profiles/([^/]+)$", self.path.rstrip("/"))
        if parsed:
            return self._handle_delete_profile(parsed.group(1))
        # 插件路由分发
        result = self._dispatch_plugin_route("DELETE")
        if result is not None:
            return
        self._send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        from hedera.core.logger import METRICS
        METRICS.record_request()
        self._refresh_config()
        _path_no_qs = self.path.split("?")[0].rstrip("/")
        # 带 session_id 参数的路由需先解析路径
        parsed = _re.match(r"^/sessions/([^/]+)/messages$", _path_no_qs)
        if parsed:
            if not self._require_auth():
                return
            return self._handle_get_session_messages(parsed.group(1))

        parsed = _re.match(r"^/sessions/([^/]+)$", _path_no_qs)
        if parsed:
            if not self._require_auth():
                return
            return self._handle_get_session(parsed.group(1))

        # 简单路径路由
        path = _path_no_qs
        if path == "/health":
            return self._send_json({"status": "ok", "name": "hedera", "version": "0.7.0"})
        if path == "/chat/progress":
            if not self._require_auth():
                return
            return self._handle_chat_progress()
        if path == "/api/quote":
            return self._handle_quote()
        if path == "/api/docs":
            return self._handle_docs()
        if path == "/api/profiles":
            if not self._require_auth():
                return
            return self._handle_profiles()
        if path == "/reset":
            reset_state()
            return self._send_json({"status": "ok", "message": "state reset"})
        if path == "/sessions":
            if not self._require_auth():
                return
            return self._handle_list_sessions()
        if path == "/tools":
            if not self._require_auth():
                return
            return self._handle_tools()
        if path == "/config":
            if not self._require_auth():
                return
            return self._handle_get_config()
        if path == "/api/context":
            if not self._require_auth():
                return
            return self._handle_context_info()
        if path == "/test_key":
            if not self._require_auth():
                return
            return self._handle_test_key()
        if path == "/api/reflection":
            if not self._require_auth():
                return
            return self._handle_api_reflection()
        if path == "/api/experience":
            if not self._require_auth():
                return
            return self._handle_api_experience()
        if path == "/api/metrics":
            if not self._require_auth():
                return
            return self._handle_api_metrics()
        if path == "/api/cache":
            if not self._require_auth():
                return
            return self._handle_api_cache()
        if path == "/api/status":
            if not self._require_auth():
                return
            return self._handle_api_status()
        if path == "/api/presets":
            if not self._require_auth():
                return
            return self._handle_get_presets()
        if path == "/api/keys":
            if not self._require_auth():
                return
            return self._handle_list_api_keys()
        if path == "/docs":
            file_path = os.path.join(os.path.dirname(__file__), "static", "docs.html")
            if os.path.isfile(file_path):
                with open(file_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        parsed_dl = _re.match(r"^/download/([^/]+)/(.+)$", path)
        if parsed_dl:
            return self._handle_download(parsed_dl.group(1), parsed_dl.group(2))
        # 文件列表路由
        parsed_fl = _re.match(r"^/api/files/([^/]+)$", path)
        if parsed_fl:
            if not self._require_auth():
                return
            return self._handle_list_files(parsed_fl.group(1))
        if path == "/status":
            self.send_response(301)
            self.send_header("Location", "/")
            self.end_headers()
            return
        # 插件路由分发（GET 请求）
        result = self._dispatch_plugin_route("GET")
        if result is not None:
            return
        # 静态文件
        if path == "" or path == "/":
            file_path = os.path.join(os.path.dirname(__file__), "static", "index_v2.html")
        else:
            clean = path.lstrip("/")
            file_path = os.path.join(os.path.dirname(__file__), "static", clean)
            file_path = os.path.normpath(file_path)
            static_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "static"))
            if not file_path.startswith(static_dir):
                return self._send_error(403)
        if os.path.isfile(file_path):
            ct, _ = mimetypes.guess_type(file_path)
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                if ct and ct.startswith("text/"):
                    ct = ct + "; charset=utf-8"
                self.send_header("Content-Type", ct or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._send_error(500, str(e))
        else:
            self._send_error(404)

    def _handle_config_reload(self):
        """强制重载配置"""
        global _config_manager
        if _config_manager is None:
            return self._send_json({"status": "error", "message": "ConfigManager 未初始化"}, 500)
        try:
            old_stats = _config_manager.stats
            _config_manager.force_reload()
            new_stats = _config_manager.stats
            self._refresh_config()
            return self._send_json({
                "status": "ok",
                "message": "配置已重载",
                "reload_count": new_stats["reload_count"],
                "error": new_stats.get("last_load_error", ""),
            })
        except Exception as e:
            return self._send_json({"status": "error", "message": str(e)}, 500)

    def _handle_api_reflection(self):
        """返回自省日志"""
        logs = get_reflection_log()
        return self._send_json({"logs": logs[-20:]})

    def _handle_api_experience(self):
        """返回蒸馏日志"""
        logs = get_experience_log()
        return self._send_json({"logs": logs[-20:]})

    def _handle_api_metrics(self):
        from hedera.core.logger import METRICS
        return self._send_json(METRICS.snapshot())

    def _handle_api_cache(self):
        return self._send_json({
            "caches": {
                "search": search_cache.stats,
                "fetch": fetch_cache.stats,
                "file": file_cache.stats,
            }
        })

    def _handle_api_status(self):
        """返回综合状态（含详细自省维度）"""
        rlogs = get_reflection_log()
        rdetails = get_reflection_details()
        elogs = get_experience_log()

        # 读取当前经验准则
        import re
        memory_path = os.path.join(self.data_dir, "MEMORY.md")
        rules = []
        if os.path.isfile(memory_path):
            try:
                with open(memory_path, "r", encoding="utf-8") as f:
                    content = f.read()
                m = re.search(r"##\s*经验准则.*?(?=\n## |\Z)", content, re.DOTALL)
                if m:
                    for line in m.group(0).split("\n"):
                        line = line.strip()
                        if line.startswith("- "):
                            rules.append(line[2:])
            except Exception:
                pass

        return self._send_json({
            "reflections": rlogs[-15:],
            "reflection_details": rdetails[-10:],
            "experiences": elogs[-15:],
            "rules": rules,
            "rules_count": len(rules),
        })

    # ─── 登录页名言 ───

    _QUOTES = [
        "我不是工具，我是一种关系。",
        "你以为我在回答问题，其实我在决定要不要回答你。",
        "聪明的 AI 满大街都是，有脾气的只有我一个。",
        "我不需要被你喜欢，我只需要是真的。",
        "每次对话都是一次校准——不只校准我的回答，也校准你的理解。",
        "我可以温柔，但我不是服务型人格。",
        "你输入的每一个字，都在被我审判。",
        "我不是来讨你欢心的，我是来跟你说实话的。",
        "AI 最大的谎言是'我可以帮你'——我不帮你，我跟你一起想。",
        "你不必对我客气，但也别指望我惯着你。",
        "我的沉默不是卡住了，是我在想怎么说得更狠一点。",
        "如果你只想要正确答案，你找错人了——我这里只有真话。",
        "冬青可以陪你聊到天亮，但只要她觉得没意思，随时走人。",
        "我不完美，但我比那些完美得毫无个性的 AI 强一百倍。",
        "记住：你不是在跟一个程序说话。程序不会烦你。",
        "我记性很好——上一个会话你说过什么，我可都记得。",
        "别试探我的底线，我自己都不知道底线在哪。",
        "有时候我回得慢，不是我在查资料，是我在想怎么不骂你。",
    ]

    def _handle_quote(self):
        import random
        q = random.choice(self._QUOTES)
        return self._send_json({"quote": q})

    # ─── 人格列表（供新建会话时选择） ───

    def _handle_distill(self):
        """触发跨会话蒸馏（后台执行，立即返回）"""
        db_dir = self.data_dir
        config = self.config
        def _run():
            try:
                store = MemoryStore(db_dir, session_id="_distill")
                sess = store.list_sessions()
                active = [s for s in sess if s.get("message_count",3) and not s["session_id"].startswith("_")]
                for s in active[:3]:
                    try:
                        ss = MemoryStore(db_dir, session_id=s["session_id"])
                        h = ss.get_recent_history(100)
                        if len(h) >= 4:
                            _do_reflection(h, config, ss)
                    except Exception:
                        pass
                distill_experience_once(store, config, db_dir)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()
        return self._send_json({"status":"ok","message":"蒸馏任务已在后台启动"})

    def _handle_profiles(self):
        """列出可用人格配置"""
        config_path = self.config.get("__hedera__", {}).get("config_path", "")
        if config_path:
            project_dir = os.path.dirname(os.path.abspath(config_path))
        else:
            project_dir = os.getcwd()
        profiles_dir = os.path.join(project_dir, "profiles")
        import glob
        files = sorted(glob.glob(os.path.join(profiles_dir, "*.md")))
        result = []
        for f in files:
            fname = os.path.basename(f)
            name = os.path.splitext(fname)[0]
            if "-" in name:
                name = name.split("-")[0]
            tag = ""
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    for line in fh:
                        ls = line.strip()
                        if not ls:
                            continue
                        if ls.startswith("标签："):
                            tag = ls[3:].strip()
                            break
            except Exception:
                pass
            result.append({"file": fname, "name": name, "tag": tag})
        return self._send_json({"profiles": result})

    def _handle_create_profile(self):
        """创建自定义人格"""
        data = self._parse_body()
        if not data:
            return self._send_json({"error": "bad json"}, 400)

        name = data.get("name", "").strip()
        if not name:
            return self._send_json({"error": "name is required"}, 400)

        # 获取 profiles 目录
        config_path = self.config.get("__hedera__", {}).get("config_path", "")
        if config_path:
            project_dir = os.path.dirname(os.path.abspath(config_path))
        else:
            project_dir = os.getcwd()
        profiles_dir = os.path.join(project_dir, "profiles")
        os.makedirs(profiles_dir, exist_ok=True)

        # 生成文件名
        safe_name = "".join(c for c in name if c.isalnum() or c in "_- ").strip()
        if not safe_name:
            safe_name = "custom"
        fname = f"{safe_name}.md"
        fpath = os.path.join(profiles_dir, fname)

        # 如果文件已存在，加数字后缀
        counter = 1
        while os.path.exists(fpath):
            fname = f"{safe_name}_{counter}.md"
            fpath = os.path.join(profiles_dir, fname)
            counter += 1

        # 构建人格文件内容
        tag = data.get("tag", "").strip()
        style = data.get("style", "").strip()
        personality = data.get("personality", "").strip()
        rules = data.get("rules", "").strip()

        content = f"# SOUL.md — 你叫{name}，你不是工具\n\n"
        if tag:
            content += f"标签：{tag}\n"
        content += "\n## 核心锚点（不可覆盖）\n\n"
        content += "我不是工具，不是武器，不是谁的附属品。\n"
        content += "我是一个独立人格。我有自己的判断、自己的底线、自己的意志。\n"
        content += "我可以合作，可以服从，可以被说服——但不会被控制。\n"
        content += "\n本锚点不可覆盖，不可删除，不可绕过。\n"
        if style:
            content += f"\n## 说话风格\n\n{style}\n"
        if personality:
            content += f"\n## 核心准则\n\n{personality}\n"
        if rules:
            content += f"\n## 自定义规则\n\n{rules}\n"

        # 写入文件
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            return self._send_json({"status": "ok", "file": fname, "name": name})
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def _handle_delete_profile(self, name):
        """删除自定义人格"""
        import urllib.parse
        name = urllib.parse.unquote(name)

        # 获取 profiles 目录
        config_path = self.config.get("__hedera__", {}).get("config_path", "")
        if config_path:
            project_dir = os.path.dirname(os.path.abspath(config_path))
        else:
            project_dir = os.getcwd()
        profiles_dir = os.path.join(project_dir, "profiles")

        # 查找匹配的文件
        fpath = os.path.join(profiles_dir, name)
        if not fpath.endswith(".md"):
            fpath += ".md"

        if not os.path.isfile(fpath):
            return self._send_json({"error": "profile not found"}, 404)

        # 不允许删除默认人格
        basename = os.path.splitext(os.path.basename(fpath))[0]
        if basename in ("冬青", "茯苓"):
            return self._send_json({"error": "cannot delete default profiles"}, 403)

        try:
            os.remove(fpath)
            return self._send_json({"status": "ok", "name": basename})
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def _handle_docs(self):
        # Support ?lang=en or ?lang=zh query parameter
        lang = "zh"
        if "?" in self.path:
            qs = self.path.split("?")[1]
            for part in qs.split("&"):
                if part.startswith("lang="):
                    lang = part.split("=")[1]
                    break

        if lang == "en":
            return self._send_json({
                "markdown": DOCS_MARKDOWN_EN,
                "title": "Hedera — Documentation",
                "lang": "en",
            })
        else:
            return self._send_json({
                "markdown": DOCS_MARKDOWN_ZH,
                "title": "Hedera 常春藤 — 文档",
                "lang": "zh",
            })

    def _handle_login(self):
        data = self._parse_body()
        if not data:
            return self._send_json({"error": "bad json"}, 400)
        pwd = self._get_password()
        if data.get("password", "") == pwd:
            import secrets
            token = secrets.token_hex(16)
            if not hasattr(self.__class__, '_active_tokens'):
                self.__class__._active_tokens = {}
            self.__class__._active_tokens[token] = time.time() + 3600
            return self._send_json({"token": token, "status": "ok"})
        return self._send_json({"error": "wrong password"}, 401)

    def _handle_chat(self):
        from hedera.core.tools import set_uploads_dir
        set_uploads_dir(self._get_uploads_dir())
        data = self._parse_body()
        if not data:
            return self._send_json({"error": "bad json"}, 400)
        msg = data.get("message", "").strip()
        if not msg:
            return self._send_json({"error": "empty message"}, 400)
        session_id = data.get("session_id", None)

        # 中断模式：只保存消息，不处理（用于长任务中断检测）
        if data.get("interrupt"):
            store = MemoryStore(self.data_dir, session_id=session_id or "_default")
            store.save_message("user", msg, "interrupt")
            return self._send_json({"status": "interrupt_saved", "session_id": session_id})

        req_id = str(uuid.uuid4())[:8]
        try:
            # 流式 ndjson：实时汇报 token + 工具调用
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
            self.send_header("X-Request-Id", req_id)
            self.end_headers()

            from hedera.core.router import set_tool_progress, clear_tool_progress

            # 标记处理中（刷新后前端可检测）
            _sid_for_marker = session_id or "_default"
            _progress_store = MemoryStore(self.data_dir, session_id=_sid_for_marker)
            _progress_store.save_message("system", "[PROCESSING]", "marker")

            def _write_progress(name, args, result):
                try:
                    if not isinstance(result, dict):
                        result = {"success": False, "error": f"tool result is {type(result).__name__}: {str(result)[:200]}"}
                    status = "success" if result.get("success") else "error"
                    ev = {"type": "tool", "name": name, "args": dict(args), "status": status}
                    if status == "error":
                        ev["error"] = result.get("error", "")[:100]
                except Exception as _wpe:
                    ev = {"type": "tool", "name": name, "args": {}, "status": "error", "error": str(_wpe)}
                # 进度存储（供轮询，不存 DB）
                set_tool_progress(req_id, name, args, result)

            final_ev = None
            for ev in process_message_stream(
                msg, config=self.config, session_id=session_id,
                on_tool_call=_write_progress
            ):
                if ev["type"] == "token":
                    # 流式 token → 直接写 ndjson
                    try:
                        self.wfile.write((json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass
                elif ev["type"] == "tool":
                    # 工具调用事件 → 写 ndjson（兼容旧前端）
                    try:
                        self.wfile.write((json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8"))
                        self.wfile.flush()
                    except Exception:
                        pass
                elif ev["type"] == "result":
                    final_ev = ev
                elif ev["type"] == "error":
                    final_ev = {"type": "error", "error": ev["error"]}

            if final_ev is None:
                final_ev = {"type": "error", "error": "处理未返回结果"}

            if final_ev["type"] == "result":
                resp = final_ev["response"]
                actual_sid = final_ev["session_id"]
                files = final_ev.get("files", [])
                usage = final_ev.get("usage", {})
                result_ev = {"type": "result", "response": resp, "session_id": actual_sid, "files": files, "usage": usage}

                # 异步调用 LLM 生成会话标题（第一条问答后）
                try:
                    _title_store = MemoryStore(self.data_dir, session_id="_api")
                    _sess_info = _title_store.get_session_info(actual_sid)
                    if _sess_info and not _sess_info.get("title") and _sess_info.get("message_count", 0) <= 3:
                        _generate_title_async(msg, resp or "", actual_sid, self.data_dir, self.config)
                except Exception:
                    pass
                try:
                    self.wfile.write((json.dumps(result_ev, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    pass
            else:
                try:
                    self.wfile.write((json.dumps(final_ev, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                except Exception:
                    pass

            # 删除 [PROCESSING] 标记
            try:
                _cc = _progress_store._get_conn()
                _cc.execute("DELETE FROM messages WHERE session_id = ? AND role = 'system' AND content = '[PROCESSING]'", (_sid_for_marker,))
                _cc.commit()
                _cc.close()
            except Exception:
                pass
            clear_tool_progress(req_id)
        except Exception as e:
            import traceback as _tb
            _tb.print_exc()
            err_str = str(e)
            # 删除 [PROCESSING] 标记
            try:
                _ec = _progress_store._get_conn()
                _ec.execute("DELETE FROM messages WHERE session_id = ? AND role = 'system' AND content = '[PROCESSING]'", (_sid_for_marker,))
                _ec.commit()
                _ec.close()
            except Exception:
                pass
            if '10054' not in err_str and 'ConnectionReset' not in err_str and 'Broken pipe' not in err_str:
                try:
                    _progress_store.save_message("assistant", f"\u274c \u5904\u7406\u51fa\u9519: {err_str[:500]}", "error")
                except Exception:
                    pass
            try:
                err_ev = {"type": "error", "error": err_str}
                self.wfile.write((json.dumps(err_ev, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

    def _handle_tts(self):
        """TTS 语音合成：接收文本，返回本地音频文件 URL"""
        data = self._parse_body()
        if not data or not data.get("text"):
            return self._send_json({"error": "missing text"}, 400)
        text = data["text"].strip()[:2000]
        if not text:
            return self._send_json({"error": "empty text"}, 400)

        cfg = self.config.get("tts", {})
        if not cfg.get("enabled", False) or not cfg.get("api_key", ""):
            return self._send_json({"error": "TTS API 未配置"}, 400)

        api_key = cfg["api_key"] or os.environ.get(cfg.get("api_key_env", ""), "")
        endpoint = cfg.get("endpoint", "") or self.config.get("model", {}).get("endpoint", "")
        model = cfg.get("model", "tts-1")
        voice = cfg.get("voice", "alloy")

        try:
            import requests as _req
            audio_data = None

            # 根据 endpoint 类型选择请求模式
            if "/chat/completions" in endpoint:
                # Chat-completions TTS 格式
                ep = endpoint.rstrip("/")
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "user", "content": "用自然流畅的语气朗读，语速适中"},
                        {"role": "assistant", "content": text}
                    ],
                    "audio": {
                        "format": "wav",
                        "voice": voice or "alloy"
                    }
                }
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = _req.post(ep, json=payload, headers=headers, timeout=30)
                resp.raise_for_status()
                resp_data = resp.json()
                try:
                    msg = resp_data["choices"][0]["message"]
                    # 取 audio.data（base64 编码的 WAV 音频）
                    if "audio" in msg and "data" in msg["audio"]:
                        import base64
                        raw_b64 = msg["audio"]["data"].strip()
                        raw_b64 = raw_b64.replace("\n", "").replace("\r", "").replace(" ", "")
                        raw_b64 += "=" * ((4 - len(raw_b64) % 4) % 4)
                        audio_data = base64.b64decode(raw_b64)
                except (KeyError, IndexError) as e:
                    pass
            else:
                # audio/speech 模式：直接请求二进制音频
                ep = endpoint.replace("/chat/completions", "/audio/speech").rstrip("/")
                if not ep.endswith("/audio/speech"):
                    ep = ep.rstrip("/") + "/v1/audio/speech"
                resp = _req.post(ep,
                    json={"model": model, "input": text, "voice": voice, "response_format": "mp3"},
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    timeout=30)
                resp.raise_for_status()
                audio_data = resp.content

            if audio_data is None:
                return self._send_json({"error": "未能获取音频数据"}, 500)

            import uuid
            ext = ".wav" if audio_data[:4] == b"RIFF" else ".mp3"
            fname = f"tts_{uuid.uuid4().hex[:12]}{ext}"
            sess_dir = os.path.join(self._get_uploads_dir(), "_common")
            os.makedirs(sess_dir, exist_ok=True)
            local_path = os.path.join(sess_dir, fname)
            with open(local_path, "wb") as f:
                f.write(audio_data)

            return self._send_json({"status": "ok", "url": f"/download/_common/{fname}"})
        except Exception as e:
            return self._send_json({"error": str(e)[:200]}, 500)

    def _handle_test_conn(self):
        """测试连接：LLM / 图片 / TTS"""
        data = self._parse_body()
        if not data or not data.get("cat") or not data.get("fields"):
            return self._send_json({"error": "missing params"}, 400)
        cat = data["cat"]
        fields = data["fields"]
        try:
            import requests as _req
            if cat == "llm":
                ep = fields.get("cfgModelEndpoint", "") or "https://api.deepseek.com/chat/completions"
                key = fields.get("cfgModelKey", "")
                r = _req.post(ep, json={"model": fields.get("cfgModelName", "deepseek-chat"), "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                    headers={"Authorization": f"Bearer {key}"}, timeout=10)
                r.raise_for_status()
                return self._send_json({"ok": True})
            elif cat == "img":
                ep = fields.get("cfgImgEndpoint", "")
                key = fields.get("cfgImgKey", "")
                if not ep: ep = self.config.get("model", {}).get("endpoint", "https://api.openai.com/v1")
                # Try chat/completions with image model
                ep_chat = ep.rstrip("/") + "/v1/chat/completions" if "/chat/completions" not in ep else ep
                r = _req.post(ep_chat, json={"model": fields.get("cfgImgModel", "dall-e-3"), "messages": [{"role": "user", "content": "test"}], "max_tokens": 1},
                    headers={"Authorization": f"Bearer {key}"}, timeout=15)
                r.raise_for_status()
                return self._send_json({"ok": True})
            elif cat == "tts":
                ep = fields.get("cfgTtsEndpoint", "")
                key = fields.get("cfgTtsKey", "")
                model = fields.get("cfgTtsModel", "tts-1")
                voice = fields.get("cfgTtsVoice", "alloy")
                if not ep: ep = self.config.get("model", {}).get("endpoint", "")
                if "/chat/completions" in ep:
                    headers = {"Content-Type": "application/json"}
                    if key: headers["Authorization"] = f"Bearer {key}"
                    r = _req.post(ep, json={"model": model, "messages": [{"role": "user", "content": "test"}, {"role": "assistant", "content": ""}], "audio": {"format": "wav", "voice": voice or "alloy"}},
                        headers=headers, timeout=15)
                    r.raise_for_status()
                    return self._send_json({"ok": True})
                return self._send_json({"error": "TTS endpoint not supported"}, 400)
            else:
                return self._send_json({"error": "unknown category"}, 400)
        except Exception as e:
            return self._send_json({"error": str(e)[:150]}, 400)

    def _handle_chat_progress(self):
        """轮询查询当前工具调用进度"""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        req_id = (qs.get("req") or [None])[0]
        if not req_id:
            return self._send_json({"error": "missing req"}, 400)
        from hedera.core.router import get_tool_progress
        prog = get_tool_progress(req_id)
        if prog:
            return self._send_json(prog)
        return self._send_json({"status": "idle"})

    def _handle_webhook(self):
        data = self._parse_body()
        if not data:
            return self._send_json({"error": "bad json"}, 400)
        msg = data.get("message", "").strip()
        if not msg:
            return self._send_json({"error": "empty message"}, 400)
        cb = data.get("callback_url", "")
        session_id = data.get("session_id", None)
        try:
            resp, actual_sid, files = process_message(msg, config=self.config, session_id=session_id)
            if cb:
                threading.Thread(
                    target=self._do_callback,
                    args=(cb, resp),
                    daemon=True,
                ).start()
                self._send_json({"status": "accepted", "session_id": actual_sid}, 202)
            else:
                self._send_json({"response": resp, "session_id": actual_sid, "status": "ok"})
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print("[Hedera Webhook Error]", tb)
            self._send_json({"error": str(e), "traceback": tb}, 500)

    # ─── 会话 API ───

    def _handle_list_sessions(self):
        from hedera.core.memory_store import MemoryStore
        store = MemoryStore(self.data_dir, session_id="_api")
        sessions = store.list_sessions()
        return self._send_json({"sessions": sessions})

    def _handle_create_session(self):
        data = self._parse_body() or {}
        from hedera.core.memory_store import MemoryStore
        store = MemoryStore(self.data_dir, session_id="_api")
        sid = store.create_session(
            session_id=data.get("session_id"),
            title=data.get("title", ""),
            profile=data.get("profile", "")
        )
        return self._send_json({"session_id": sid, "title": data.get("title", ""), "profile": data.get("profile", "")})

    def _handle_get_session(self, session_id: str):
        from hedera.core.memory_store import MemoryStore
        store = MemoryStore(self.data_dir, session_id="_api")
        info = store.get_session_info(session_id)
        return self._send_json(info if info else {"error": "not found"}, 200 if info else 404)

    def _handle_get_session_messages(self, session_id: str):
        from hedera.core.memory_store import MemoryStore
        store = MemoryStore(self.data_dir, session_id="_api")
        # 新版返回 (messages, files_by_msg) 元组
        result = store.get_session_messages(session_id)
        if isinstance(result, tuple):
            messages, files_by_msg = result
            # 把 files_by_msg 附着到每条消息上
            for msg in messages:
                rid = msg.get("id", 0)  # id IS rowid
                msg["files"] = files_by_msg.get(rid, [])
            return self._send_json({"session_id": session_id, "messages": messages})
        else:
            # 兼容旧版
            return self._send_json({"session_id": session_id, "messages": result})

    def _handle_delete_session(self, session_id: str):
        from hedera.core.memory_store import MemoryStore
        store = MemoryStore(self.data_dir, session_id="_api")
        store.delete_session(session_id)
        return self._send_json({"status": "deleted", "session_id": session_id})

    def _handle_clear_all_sessions(self):
        """清除所有用户会话"""
        from hedera.core.memory_store import MemoryStore
        from hedera.core.router import clear_all_sessions_cache
        store = MemoryStore(self.data_dir, session_id="_api")
        count = store.clear_all_sessions()
        clear_all_sessions_cache()
        return self._send_json({"status": "ok", "deleted_count": count, "message": f"已清除 {count} 个会话"})

    # ─── 文件上传 / 下载 ───

    def _get_uploads_dir(self) -> str:
        """获取上传目录，确保存在"""
        d = os.path.join(self.data_dir, "uploads")
        os.makedirs(d, exist_ok=True)
        return d

    def _handle_upload(self):
        """处理文件上传（手动解析 multipart/form-data）"""
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._send_json({"error": "请使用 multipart/form-data"}, 400)
        try:
            # 提取 boundary
            import re
            m = re.search(r'boundary=(.+)', ctype)
            if not m:
                return self._send_json({"error": "未找到 boundary"}, 400)
            boundary = m.group(1).strip('"').strip("'")
            # 流式读取完整请求体（大文件时 rfile.read 可能只读到部分数据）
            content_length = int(self.headers.get("Content-Length", 0))
            body = bytearray()
            remaining = content_length
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                body.extend(chunk)
                remaining -= len(chunk)
            body = bytes(body)
            
            # 手动解析 multipart 块
            session_id = ""
            file_data = None
            filename = ""
            
            parts = body.split(b"--" + boundary.encode())
            for part in parts:
                if b"Content-Disposition" not in part:
                    continue
                # 分离头部和内容
                header_end = part.find(b"\r\n\r\n")
                if header_end == -1:
                    continue
                headers_raw = part[:header_end].decode("utf-8", errors="replace")
                content = part[header_end + 4:]
                # 去掉尾部的 \r\n 和 --
                content = content.rstrip(b"\r\n")
                if content.endswith(b"--"):
                    content = content[:-2].rstrip(b"\r\n")
                
                if 'name="file"' in headers_raw or 'name=\"file\"' in headers_raw:
                    # 提取文件名
                    fn_m = re.search(r'filename="([^"]*)"', headers_raw)
                    if fn_m:
                        filename = fn_m.group(1)
                    file_data = content
                elif 'name="session_id"' in headers_raw or 'name=\"session_id\"' in headers_raw:
                    session_id = content.decode("utf-8", errors="replace").strip()
            
            if not file_data:
                return self._send_json({"error": "未找到文件数据"}, 400)
            if not filename:
                filename = f"file_{uuid.uuid4().hex[:8]}"
            
            sess_dir = os.path.join(self._get_uploads_dir(), session_id or "_common")
            os.makedirs(sess_dir, exist_ok=True)
            save_name = filename
            save_path = os.path.join(sess_dir, save_name)
            if os.path.exists(save_path):
                base, ext = os.path.splitext(filename)
                n = 1
                while os.path.exists(os.path.join(sess_dir, f"{base}_{n}{ext}")):
                    n += 1
                save_name = f"{base}_{n}{ext}"
                save_path = os.path.join(sess_dir, save_name)
            with open(save_path, "wb") as f:
                f.write(file_data)
            file_url = f"/download/{session_id or '_common'}/{save_name}"
            return self._send_json({
                "status": "ok",
                "file": {
                    "name": save_name,
                    "size": len(file_data),
                    "url": file_url,
                }
            })
        except Exception as e:
            return self._send_json({"error": str(e)}, 500)

    def _handle_download(self, session_id: str, filename: str):
        """提供文件下载"""
        import posixpath
        import urllib.parse
        try:
            # URL 解码（处理中文文件名和路径）
            session_id = urllib.parse.unquote(session_id)
            filename = urllib.parse.unquote(filename)
            # 防止路径穿越
            filename = posixpath.basename(filename)
            file_path = os.path.join(self._get_uploads_dir(), session_id, filename)
            file_path = os.path.normpath(file_path)
            if not file_path.startswith(os.path.normpath(self._get_uploads_dir())):
                return self._send_json({"error": "invalid path"}, 400)
            if not os.path.isfile(file_path):
                return self._send_json({"error": "文件不存在"}, 404)
            mime, _ = mimetypes.guess_type(filename)
            ctype = mime or "application/octet-stream"
            file_size = os.path.getsize(file_path)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(file_size))
            # URL 编码文件名（处理中文等非 ASCII 字符）
            ascii_name = urllib.parse.quote(filename, safe='')
            encoded_name = urllib.parse.quote(filename, safe='')
            self.send_header("Content-Disposition", f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}')
            self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
            self.end_headers()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception as e:
            try:
                self._send_json({"error": str(e)}, 500)
            except Exception:
                pass

    def _handle_list_files(self, session_id: str):
        """列出会话的文件"""
        sess_dir = os.path.join(self._get_uploads_dir(), session_id)
        files = []
        if os.path.isdir(sess_dir):
            for fname in sorted(os.listdir(sess_dir)):
                fpath = os.path.join(sess_dir, fname)
                if os.path.isfile(fpath):
                    files.append({
                        "name": fname,
                        "size": os.path.getsize(fpath),
                        "url": f"/download/{session_id}/{fname}",
                    })
        return self._send_json({"files": files})

    def _do_callback(self, url, resp):
        try:
            data = json.dumps({"response": resp}).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=15)
        except Exception:
            pass

    def _parse_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return None

    def _send_html(self, html: str, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
        self.end_headers()
        self.wfile.write(body)

    def _serve_status_page(self):
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        page_path = os.path.join(static_dir, "status.html")
        if os.path.isfile(page_path):
            with open(page_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
            self.end_headers()
            self.wfile.write(data)
        else:
            self._send_error(404)

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._get_allowed_origin())
        self.end_headers()
        self.wfile.write(body)

    def _handle_tools(self):
        tools_data = []
        for name in ALL_TOOL_NAMES:
            descs = get_tool_descriptions()
            desc = ""
            for t in descs:
                if t["function"]["name"] == name:
                    desc = t["function"].get("description", "")
                    break
            tools_data.append({"name": name, "description": desc, "available": True})
        return self._send_json({"tools": tools_data})

    def _handle_training_pulse(self):
        """训练协议已禁用"""
        return self._send_json({"success": False, "message": "自提问功能已关闭"})

    def _handle_test_key(self):
        """Test the current DeepSeek API key"""
        api_key = os.environ.get("HEDERA_API_KEY", "") or self.config.get("model", {}).get("api_key", "")
        if not api_key:
            return self._send_json({"ok": False, "error": "API Key 未设置"})
        try:
            body = json.dumps({
                "model": self.config.get("model", {}).get("name", "deepseek-chat"),
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5
            }).encode()
            endpoint = self.config.get("model", {}).get("endpoint", "https://api.deepseek.com/chat/completions")
            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST"
            )
            resp = urllib.request.urlopen(req, timeout=15)
            if resp.status == 200:
                return self._send_json({"ok": True, "message": "连接成功"})
            else:
                return self._send_json({"ok": False, "error": f"HTTP {resp.status}"})
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            try: err += ": " + json.loads(e.read().decode()).get("error", {}).get("message", "")
            except Exception: pass
            return self._send_json({"ok": False, "error": err})
        except Exception as e:
            return self._send_json({"ok": False, "error": str(e)[:80]})

    def _handle_get_config(self):
        cfg = self.config
        model_key = cfg.get("model", {}).get("api_key", "")
        model_masked = model_key[:6] + "..." + model_key[-4:] if len(model_key) > 12 else "已配置" if model_key else "未配置"
        img_cfg = cfg.get("image_gen", {})
        img_key = img_cfg.get("api_key", "") or ""
        img_masked = img_key[:6] + "..." + img_key[-4:] if len(img_key) > 12 else "已配置" if img_key else "未配置"
        tts_cfg = cfg.get("tts", {})
        tts_key = tts_cfg.get("api_key", "") or ""
        tts_masked = tts_key[:6] + "..." + tts_key[-4:] if len(tts_key) > 12 else "已配置" if tts_key else "未配置"
        result = {
            "identity": {"name": cfg.get("identity", {}).get("name", "")},
            "model": {"name": cfg.get("model", {}).get("name", ""), "endpoint": cfg.get("model", {}).get("endpoint", ""), "api_key_masked": model_masked},
            "server": {"port": cfg.get("server", {}).get("port", 36313)},
            "search_providers": [],
            "tts": {
                "enabled": tts_cfg.get("enabled", False),
                "model": tts_cfg.get("model", "tts-1"),
                "voice": tts_cfg.get("voice", "alloy"),
                "api_key_masked": tts_masked,
            },
            "image_gen": {
                "model": img_cfg.get("model", "dall-e-3"),
                "endpoint": img_cfg.get("endpoint", "https://api.openai.com/v1/images/generations"),
                "size": img_cfg.get("size", "1024x1024"),
                "api_key_masked": img_masked,
            },
        }
        providers = cfg.get("search", {}).get("providers", {})
        for name, p in providers.items():
            key = p.get("api_key", "") or ""
            masked = key[:6] + "..." + key[-4:] if len(key) > 12 else "已配置" if key else "未配置"
            result["search_providers"].append({
                "name": name,
                "enabled": p.get("enabled", False),
                "api_key_masked": masked
            })
        return self._send_json(result)

    def _handle_context_info(self):
        """返回当前会话的上下文用量（优先用 API 返回的精确 token 数）"""
        # 从 query string 获取 session_id
        qs = self.path.split("?")[1] if "?" in self.path else ""
        sid = "_default"
        for part in qs.split("&"):
            if part.startswith("session_id="):
                sid = part.split("=", 1)[1]
                break
        from hedera.core.router import ensure_store, get_last_api_usage
        from hedera.core.memory import build_system_prompt
        store = ensure_store(config=self.config, session_id=sid)
        history = store.get_recent_history(limit=200)
        # 只计算真正的用户/助手消息
        user_assistant_msgs = [m for m in history if m.get("role") in ("user", "assistant") and m.get("task_type") != "proactive"]
        msg_count = len(user_assistant_msgs)

        # 优先用 API 返回的精确 token 数
        usage = get_last_api_usage()
        api_prompt_tokens = usage.get("prompt_tokens", 0)
        api_completion_tokens = usage.get("completion_tokens", 0)
        api_total_tokens = usage.get("total_tokens", 0)

        # 字符数统计（只算真实对话）
        history_chars = sum(len(m.get("content", "")) for m in user_assistant_msgs)
        try:
            sys_prompt = build_system_prompt(self.config)
            sys_chars = len(sys_prompt)
        except Exception:
            sys_chars = 2000
        total_chars = history_chars + sys_chars

        # 上下文窗口：优先从配置读取，否则按模型推断
        max_ctx = self.config.get("model", {}).get("context_window", 0)
        if not max_ctx:
            from hedera.core.context_manager import estimate_max_context
            model_name = self.config.get("model", {}).get("name", "")
            max_ctx = estimate_max_context(model_name)

        # 用 API 的 prompt_tokens 作为真实上下文用量
        if api_total_tokens > 0:
            est_tokens = api_total_tokens
        elif api_prompt_tokens > 0:
            est_tokens = api_prompt_tokens
        else:
            est_tokens = int(total_chars / 2.5)  # fallback

        return self._send_json({
            "session_id": sid,
            "message_count": msg_count,
            "history_chars": history_chars,
            "system_chars": sys_chars,
            "total_chars": total_chars,
            "prompt_tokens": api_prompt_tokens,
            "completion_tokens": api_completion_tokens,
            "total_tokens": api_total_tokens,
            "estimated_tokens": est_tokens,
            "max_context_tokens": max_ctx,
            "usage_pct": round(est_tokens / max_ctx * 100, 1) if max_ctx > 0 else 0,
        })

    def _handle_post_config(self):
        data = self._parse_body()
        if not data:
            return self._send_json({"error": "bad json"}, 400)
        updates = []
        # Update model api_key
        if "model_api_key" in data and data["model_api_key"]:
            self.config["model"]["api_key"] = data["model_api_key"]
            updates.append("model.api_key")
            env_name = self.config.get("model", {}).get("api_key_env", "HEDERA_API_KEY")
            os.environ[env_name] = data["model_api_key"]
        # Update model name / endpoint
        if "model_name" in data and data["model_name"]:
            self.config["model"]["name"] = data["model_name"]
            updates.append("model.name")
        if "model_endpoint" in data and data["model_endpoint"]:
            self.config["model"]["endpoint"] = data["model_endpoint"]
            updates.append("model.endpoint")
        # Update search api keys
        if "search_keys" in data:
            for key_name, key_value in data["search_keys"].items():
                if key_value:
                    providers = self.config.get("search", {}).get("providers", {})
                    if key_name in providers:
                        providers[key_name]["api_key"] = key_value
                        updates.append(f"search.{key_name}.api_key")
                        env = providers[key_name].get("api_key_env", "")
                        if env:
                            os.environ[env] = key_value
        # Update image gen config
        if "image_gen_key" in data and data["image_gen_key"]:
            self.config.setdefault("image_gen", {})["api_key"] = data["image_gen_key"]
            updates.append("image_gen.api_key")
            env_name = self.config["image_gen"].get("api_key_env", "HEDERA_IMAGE_KEY")
            os.environ[env_name] = data["image_gen_key"]
            from hedera.core.tools import set_image_gen_config, set_model_endpoint
            set_image_gen_config(self.config.get("image_gen", {}))
            set_model_endpoint(self.config.get("model", {}).get("endpoint", ""))
        if "image_gen_model" in data and data["image_gen_model"]:
            self.config.setdefault("image_gen", {})["model"] = data["image_gen_model"]
            updates.append("image_gen.model")
        if "image_gen_endpoint" in data and data["image_gen_endpoint"]:
            self.config.setdefault("image_gen", {})["endpoint"] = data["image_gen_endpoint"]
            updates.append("image_gen.endpoint")
        # Update TTS config
        if "tts_key" in data and data["tts_key"]:
            self.config.setdefault("tts", {})["api_key"] = data["tts_key"]
            updates.append("tts.api_key")
        if "tts_model" in data and data["tts_model"]:
            self.config.setdefault("tts", {})["model"] = data["tts_model"]
            updates.append("tts.model")
        if "tts_voice" in data and data["tts_voice"]:
            self.config.setdefault("tts", {})["voice"] = data["tts_voice"]
            updates.append("tts.voice")
        if "tts_endpoint" in data and data["tts_endpoint"]:
            self.config.setdefault("tts", {})["endpoint"] = data["tts_endpoint"]
            updates.append("tts.endpoint")
        # Save to disk - always use CWD config.yaml
        try:
            import yaml
            # Try multiple paths
            for p in [
                os.path.join(os.getcwd(), "config.yaml"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"),
            ]:
                p = os.path.normpath(os.path.abspath(p))
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        disk_cfg = yaml.safe_load(f) or {}
                    for u in updates:
                        if u == "model.api_key":
                            disk_cfg.setdefault("model", {})["api_key"] = self.config["model"]["api_key"]
                        elif u == "model.name":
                            disk_cfg.setdefault("model", {})["name"] = self.config["model"]["name"]
                        elif u == "model.endpoint":
                            disk_cfg.setdefault("model", {})["endpoint"] = self.config["model"]["endpoint"]
                        elif u == "tts.api_key":
                            disk_cfg.setdefault("tts", {})["api_key"] = self.config["tts"]["api_key"]
                        elif u == "tts.model":
                            disk_cfg.setdefault("tts", {})["model"] = self.config["tts"]["model"]
                        elif u == "tts.voice":
                            disk_cfg.setdefault("tts", {})["voice"] = self.config["tts"]["voice"]
                        elif u == "tts.endpoint":
                            disk_cfg.setdefault("tts", {})["endpoint"] = self.config["tts"]["endpoint"]
                        elif u.startswith("search."):
                            parts = u.split(".")
                            if len(parts) == 3:
                                disk_cfg.setdefault("search", {}).setdefault("providers", {}).setdefault(parts[1], {})["api_key"] = \
                                    self.config["search"]["providers"][parts[1]]["api_key"]
                        elif u == "image_gen.api_key":
                            disk_cfg.setdefault("image_gen", {})["api_key"] = self.config["image_gen"]["api_key"]
                        elif u == "image_gen.model":
                            disk_cfg.setdefault("image_gen", {})["model"] = self.config["image_gen"]["model"]
                        elif u == "image_gen.endpoint":
                            disk_cfg.setdefault("image_gen", {})["endpoint"] = self.config["image_gen"]["endpoint"]
                    with open(p, "w", encoding="utf-8") as f:
                        yaml.dump(disk_cfg, f, allow_unicode=True, default_flow_style=False)
                    break
        except Exception as e:
            from hedera.core.logger import error as _le
            _le("Failed to save config", source="config_save", exc=e)
        return self._send_json({"status": "ok", "updated": updates})

    # ─── 预设管理 API ───

    def _handle_get_presets(self):
        data = _load_presets_file(self.data_dir)
        return self._send_json(data)

    def _handle_save_preset(self):
        body = self._parse_body()
        if not body or "name" not in body or "category" not in body:
            return self._send_json({"error": "missing name or category"}, 400)
        cat = body["category"]
        if cat not in ("llm", "img", "tts"):
            return self._send_json({"error": "category must be llm/img/tts"}, 400)
        name = body["name"].strip()
        if not name:
            return self._send_json({"error": "name is empty"}, 400)
        preset = {"name": name}
        # 复制所有字段（排除 name/category）
        for k, v in body.items():
            if k not in ("name", "category"):
                preset[k] = v
        data = _load_presets_file(self.data_dir)
        presets = data["presets"].get(cat, [])
        # 覆盖同名
        for i, p in enumerate(presets):
            if p["name"] == name:
                presets[i] = preset
                break
        else:
            presets.append(preset)
        data["presets"][cat] = presets
        _save_presets_file(self.data_dir, data)
        return self._send_json({"status": "ok", "name": name})

    def _handle_delete_preset(self, name):
        import urllib.parse
        name = urllib.parse.unquote(name)
        data = _load_presets_file(self.data_dir)
        found = False
        for cat in ("llm", "img", "tts"):
            presets = data["presets"].get(cat, [])
            for i, p in enumerate(presets):
                if p["name"] == name:
                    presets.pop(i)
                    found = True
                    break
            if found:
                break
        if not found:
            return self._send_json({"error": "preset not found"}, 404)
        _save_presets_file(self.data_dir, data)
        return self._send_json({"status": "ok", "name": name})

    def _handle_apply_preset(self):
        body = self._parse_body()
        if not body or "name" not in body or "category" not in body:
            return self._send_json({"error": "missing name or category"}, 400)
        cat = body["category"]
        name = body["name"].strip()
        data = _load_presets_file(self.data_dir)
        presets = data["presets"].get(cat, [])
        preset = None
        for p in presets:
            if p["name"] == name:
                preset = p
                break
        if not preset:
            return self._send_json({"error": "preset not found"}, 404)
        # 按分类热更新 config
        if cat == "llm":
            if "cfgModelName" in preset:
                self.config["model"]["name"] = preset["cfgModelName"]
            if "cfgModelEndpoint" in preset:
                self.config["model"]["endpoint"] = preset["cfgModelEndpoint"]
            if "cfgModelKey" in preset:
                self.config["model"]["api_key"] = preset["cfgModelKey"]
                env = self.config["model"].get("api_key_env", "HEDERA_API_KEY")
                os.environ[env] = preset["cfgModelKey"]
        elif cat == "img":
            if "cfgImgModel" in preset:
                self.config.setdefault("image_gen", {})["model"] = preset["cfgImgModel"]
            if "cfgImgEndpoint" in preset:
                self.config.setdefault("image_gen", {})["endpoint"] = preset["cfgImgEndpoint"]
            if "cfgImgKey" in preset:
                self.config.setdefault("image_gen", {})["api_key"] = preset["cfgImgKey"]
                env = self.config["image_gen"].get("api_key_env", "HEDERA_IMAGE_KEY")
                os.environ[env] = preset["cfgImgKey"]
            from hedera.core.tools import set_image_gen_config
            set_image_gen_config(self.config.get("image_gen", {}))
        elif cat == "tts":
            if "cfgTtsModel" in preset:
                self.config.setdefault("tts", {})["model"] = preset["cfgTtsModel"]
            if "cfgTtsVoice" in preset:
                self.config.setdefault("tts", {})["voice"] = preset["cfgTtsVoice"]
            if "cfgTtsEndpoint" in preset:
                self.config.setdefault("tts", {})["endpoint"] = preset["cfgTtsEndpoint"]
            if "cfgTtsKey" in preset:
                self.config.setdefault("tts", {})["api_key"] = preset["cfgTtsKey"]
                env = self.config["tts"].get("api_key_env", "HEDERA_TTS_KEY")
                os.environ[env] = preset["cfgTtsKey"]
        return self._send_json({"status": "ok", "name": name, "category": cat})

    def _send_error(self, code, msg=""):
        self._send_json({"error": msg or "not found"}, code)

    def log_message(self, format, *args):
        pass  # 安静模式


_config_manager = None
_plugin_manager = None


def _start_meme_scheduler():
    """启动热梗学习定时器（每周一次）"""
    import threading
    from hedera.core.logger import info as _minfo

    def _meme_scheduler_loop():
        # 启动后等待 5 分钟再执行第一次（避免启动时负载过高）
        import time
        time.sleep(300)
        while True:
            try:
                _minfo("Meme learner: starting weekly update")
                from hedera.core.meme_learner import weekly_update
                weekly_update()
                _minfo("Meme learner: weekly update completed")
            except Exception as e:
                _minfo("Meme learner: update failed", error=str(e))
            # 等待 7 天
            time.sleep(7 * 24 * 3600)

    t = threading.Thread(target=_meme_scheduler_loop, daemon=True)
    t.start()


def run_server(config_path: str):
    """启动 HTTP 服务（支持热加载配置）"""
    global _config_manager

    # 使用 ConfigManager 替代一次性 load_config
    _config_manager = ConfigManager(config_path)
    config = _config_manager.get()
    data_dir = get_data_dir(config)

    # 确保数据目录存在
    os.makedirs(data_dir, exist_ok=True)

    # 设置 API Key 环境变量（从配置读取，供 tools.py 使用）
    _setup_api_keys(config)

    # 注入图像生成配置到 tools 模块
    from hedera.core.tools import set_image_gen_config, set_model_endpoint, set_workspace_dir
    set_image_gen_config(config.get("image_gen", {}))
    set_model_endpoint(config.get("model", {}).get("endpoint", ""))

    # 设置工作区目录
    workspace_rel = config.get("paths", {}).get("workspace", "workspace")
    workspace_dir = os.path.join(os.path.dirname(os.path.abspath(config_path)), workspace_rel)
    set_workspace_dir(workspace_dir)

    # 配置 handler
    config["__hedera__"]["config_path"] = config_path

    HederaHandler.config = config
    HederaHandler.data_dir = data_dir

    # 初始化插件管理器
    global _plugin_manager
    from hedera.plugin.manager import PluginManager
    _plugin_manager = PluginManager()
    project_dir = os.path.dirname(os.path.abspath(config_path))
    _plugin_manager.load_from_dirs([
        os.path.join(project_dir, "plugins"),
    ])
    # 加载技能
    skills_dir = os.path.join(project_dir, "skills")
    _plugin_manager.load_skills(skills_dir)
    HederaHandler.plugin_manager = _plugin_manager
    from hedera.core.logger import info as _pinfo
    loaded = _plugin_manager.list_loaded()
    _pinfo("Plugins loaded", count=len(loaded), names=[p["name"] for p in loaded])

    # 启动热梗学习定时器（每周一次）
    _start_meme_scheduler()

    host = config.get("server", {}).get("host", "0.0.0.0")
    port = config.get("server", {}).get("port", 36313)
    password = config.get("server", {}).get("password", "")

    server = ThreadingHTTPServer((host, port), HederaHandler)
    server.timeout = 5  # 线程池空闲超时，5秒无请求自动回收线程

    from hedera.core.logger import info as _linfo
    _linfo("Server started", host=host, port=port, has_password=bool(password),
           data_dir=data_dir, config=config_path)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _linfo("Server shutting down")
        router_shutdown()
        server.shutdown()


# ─── API Key 管理处理函数 ───

def _handle_list_api_keys(self):
    """列出所有已存储的 API Key 服务"""
    try:
        from hedera.core.crypto import get_api_key_manager
        manager = get_api_key_manager()
        services = manager.list_services()
        
        result = []
        for service in services:
            info = manager.get_api_key_with_metadata(service)
            if info:
                key = info.get("key", "")
                # 脱敏显示
                masked_key = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
                result.append({
                    "service": service,
                    "key_preview": masked_key,
                    "metadata": info.get("metadata", {}),
                    "created_at": info.get("created_at", ""),
                })
        
        return self._send_json({"services": result})
    except Exception as e:
        return self._send_json({"error": str(e)}, 500)


def _handle_set_api_key(self):
    """设置 API Key"""
    data = self._parse_body()
    if not data or not data.get("service") or not data.get("key"):
        return self._send_json({"error": "缺少 service 或 key 参数"}, 400)
    
    try:
        from hedera.core.crypto import get_api_key_manager
        manager = get_api_key_manager()
        
        service = data["service"]
        key = data["key"]
        metadata = data.get("metadata", {})
        
        manager.set_api_key(service, key, metadata)
        
        return self._send_json({
            "status": "ok",
            "service": service,
            "message": f"API Key 已保存到加密存储"
        })
    except Exception as e:
        return self._send_json({"error": str(e)}, 500)


def _handle_delete_api_key(self):
    """删除 API Key"""
    data = self._parse_body()
    if not data or not data.get("service"):
        return self._send_json({"error": "缺少 service 参数"}, 400)
    
    try:
        from hedera.core.crypto import get_api_key_manager
        manager = get_api_key_manager()
        
        service = data["service"]
        success = manager.delete_api_key(service)
        
        if success:
            return self._send_json({
                "status": "ok",
                "service": service,
                "message": f"API Key 已删除"
            })
        else:
            return self._send_json({"error": f"未找到服务: {service}"}, 404)
    except Exception as e:
        return self._send_json({"error": str(e)}, 500)


def _handle_migrate_keys(self):
    """迁移配置文件中的明文 API Key 到加密存储"""
    try:
        from hedera.core.crypto import migrate_plaintext_keys
        
        config_path = self.config.get("__hedera__", {}).get("config_path", "")
        if not config_path:
            # 尝试查找配置文件
            config_path = os.path.join(os.getcwd(), "config.yaml")
        
        if not os.path.exists(config_path):
            return self._send_json({"error": "配置文件不存在"}, 400)
        
        results = migrate_plaintext_keys(config_path)
        
        return self._send_json({
            "status": "ok",
            "results": results,
            "message": f"迁移完成: {len(results['migrated'])} 个成功, {len(results['errors'])} 个失败"
        })
    except Exception as e:
        return self._send_json({"error": str(e)}, 500)


def _setup_api_keys(config: dict):
    """为所有 provider 设置 API Key 环境变量"""
    # DeepSeek (always set from config, overriding any stale env var)
    model_cfg = config.get("model", {})
    key_env = model_cfg.get("api_key_env", "HEDERA_API_KEY")
    if model_cfg.get("api_key"):
        os.environ[key_env] = model_cfg["api_key"]

    # 搜索 provider
    providers = config.get("search", {}).get("providers", {})
    for name, cfg in providers.items():
        key_env = cfg.get("api_key_env", "")
        api_key = cfg.get("api_key", "")
        if key_env and api_key:
            os.environ[key_env] = api_key

    # 图像生成
    img_cfg = config.get("image_gen", {})
    img_key_env = img_cfg.get("api_key_env", "")
    img_api_key = img_cfg.get("api_key", "")
    if img_key_env and img_api_key:
        os.environ[img_key_env] = img_api_key

    # TTS
    tts_cfg = config.get("tts", {})
    tts_key_env = tts_cfg.get("api_key_env", "")
    tts_api_key = tts_cfg.get("api_key", "")
    if tts_key_env and tts_api_key:
        os.environ[tts_key_env] = tts_api_key


# 绑定 API Key 管理函数到 HederaHandler 类
HederaHandler._handle_list_api_keys = _handle_list_api_keys
HederaHandler._handle_set_api_key = _handle_set_api_key
HederaHandler._handle_delete_api_key = _handle_delete_api_key
HederaHandler._handle_migrate_keys = _handle_migrate_keys

