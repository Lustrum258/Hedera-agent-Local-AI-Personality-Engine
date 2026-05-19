"""
Hedera HTTP 服务
基于 Python 内置 http.server，零依赖 Web 服务。
"""

import os
import sys
import json
import base64
import threading
import mimetypes
import time
import uuid
import urllib.request
import re as _re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Callable

from hedera.config import ConfigManager, load_config, get_data_dir
from hedera.docs import DOCS_MARKDOWN
from hedera.core.router import (
    process_message, reset_state, shutdown as router_shutdown,
    get_reflection_log, get_reflection_details, get_experience_log,
    _do_reflection,
)
from hedera.core.memory_store import MemoryStore
from hedera.core.experience import distill_experience_once
from hedera.core.tools import ALL_TOOL_NAMES, get_tool_descriptions
from hedera.core.cache import search_cache, fetch_cache, file_cache


class HederaHandler(BaseHTTPRequestHandler):
    config = {}
    data_dir = ""

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
                new_pwd = self.config.get("server", {}).get("password", "")
                from hedera.core.logger import info as _li
                _li("Config hot-reloaded", password_changed=bool(old_pwd and old_pwd != new_pwd))

    def _get_password(self):
        return self.config.get("server", {}).get("password", "")

    def _check_auth(self):
        pwd = self._get_password()
        if not pwd:
            return True  # 没设密码就不验证
        auth = self.headers.get("Authorization", "")
        return auth.startswith("Bearer ") and auth[7:] == pwd

    def _require_auth(self):
        if not self._check_auth():
            self._send_json({"error": "未授权"}, 401)
            return False
        return True

    def do_POST(self):
        from hedera.core.logger import METRICS
        METRICS.record_request()
        self._refresh_config()
        path = self.path.rstrip("/")
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
        elif path == "/sessions":
            return self._handle_create_session()
        elif path == "/sessions/clear_all":
            return self._handle_clear_all_sessions()
        elif path == "/api/distill":
            return self._handle_distill()
        elif path == "/upload":
            return self._handle_upload()
        else:
            self._send_error(404)

    def do_DELETE(self):
        if not self._require_auth():
            return
        parsed = _re.match(r"^/sessions/([^/]+)$", self.path.rstrip("/"))
        if parsed:
            return self._handle_delete_session(parsed.group(1))
        self._send_error(404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self):
        from hedera.core.logger import METRICS
        METRICS.record_request()
        self._refresh_config()
        # 带 session_id 参数的路由需先解析路径
        parsed = _re.match(r"^/sessions/([^/]+)/messages$", self.path.rstrip("/"))
        if parsed:
            if not self._require_auth():
                return
            return self._handle_get_session_messages(parsed.group(1))

        parsed = _re.match(r"^/sessions/([^/]+)$", self.path.rstrip("/"))
        if parsed:
            if not self._require_auth():
                return
            return self._handle_get_session(parsed.group(1))

        # 简单路径路由
        path = self.path.rstrip("/")
        if path == "/health":
            return self._send_json({"status": "ok", "name": "hedera", "version": "0.7.0"})
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
        # 文件下载路由（不需认证，浏览器直接打开）
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
            return self._serve_status_page()
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
                self.send_header("Content-Type", ct or "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
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
            except:
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
                    except:
                        pass
                distill_experience_once(store, config, db_dir)
            except:
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
            except:
                pass
            result.append({"file": fname, "name": name, "tag": tag})
        return self._send_json({"profiles": result})

    def _handle_docs(self):
        return self._send_json({
            "markdown": DOCS_MARKDOWN,
            "title": "Hedera 常春藤 — 文档",
        })

    def _handle_login(self):
        data = self._parse_body()
        if not data:
            return self._send_json({"error": "bad json"}, 400)
        pwd = self._get_password()
        if data.get("password", "") == pwd:
            return self._send_json({"token": pwd, "status": "ok"})
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
        try:
            resp, actual_sid, files = process_message(msg, config=self.config, session_id=session_id)
            self._send_json({"response": resp, "session_id": actual_sid, "status": "ok", "files": files})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

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
            self._send_json({"error": str(e)}, 500)

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
        store = MemoryStore(self.data_dir, session_id="_api")
        count = store.clear_all_sessions()
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
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            
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
            self.send_header("Access-Control-Allow-Origin", "*")
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
        self.send_header("Access-Control-Allow-Origin", "*")
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
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        else:
            self._send_error(404)

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
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
            except: pass
            return self._send_json({"ok": False, "error": err})
        except Exception as e:
            return self._send_json({"ok": False, "error": str(e)[:80]})

    def _handle_get_config(self):
        cfg = self.config
        model_key = cfg.get("model", {}).get("api_key", "")
        model_masked = model_key[:6] + "..." + model_key[-4:] if len(model_key) > 12 else "已配置" if model_key else "未配置"
        result = {
            "identity": {"name": cfg.get("identity", {}).get("name", "")},
            "model": {"name": cfg.get("model", {}).get("name", ""), "endpoint": cfg.get("model", {}).get("endpoint", ""), "api_key_masked": model_masked},
            "server": {"port": cfg.get("server", {}).get("port", 36313)},
            "search_providers": [],
        }
        providers = cfg.get("search", {}).get("providers", {})
        for name, p in providers.items():
            key = p.get("api_key", "")
            masked = key[:6] + "..." + key[-4:] if len(key) > 12 else "已配置" if key else "未配置"
            result["search_providers"].append({
                "name": name,
                "enabled": p.get("enabled", False),
                "api_key_masked": masked
            })
        return self._send_json(result)

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
                        elif u.startswith("search."):
                            parts = u.split(".")
                            if len(parts) == 3:
                                disk_cfg.setdefault("search", {}).setdefault("providers", {}).setdefault(parts[1], {})["api_key"] = \
                                    self.config["search"]["providers"][parts[1]]["api_key"]
                    with open(p, "w", encoding="utf-8") as f:
                        yaml.dump(disk_cfg, f, allow_unicode=True, default_flow_style=False)
                    break
        except Exception as e:
            from hedera.core.logger import error as _le
            _le("Failed to save config", source="config_save", exc=e)
        return self._send_json({"status": "ok", "updated": updates})

    def _send_error(self, code, msg=""):
        self._send_json({"error": msg or "not found"}, code)

    def log_message(self, format, *args):
        pass  # 安静模式


_config_manager = None


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

    # 配置 handler
    config["__hedera__"]["config_path"] = config_path

    HederaHandler.config = config
    HederaHandler.data_dir = data_dir

    host = config.get("server", {}).get("host", "0.0.0.0")
    port = config.get("server", {}).get("port", 36313)
    password = config.get("server", {}).get("password", "")

    server = ThreadingHTTPServer((host, port), HederaHandler)

    from hedera.core.logger import info as _linfo
    _linfo("Server started", host=host, port=port, has_password=bool(password),
           data_dir=data_dir, config=config_path)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _linfo("Server shutting down")
        router_shutdown()
        server.shutdown()


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

