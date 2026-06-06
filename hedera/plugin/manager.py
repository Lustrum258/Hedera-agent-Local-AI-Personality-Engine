"""
Hedera 插件管理器
扫描目录 → 加载插件 → 注册工具 → 注册路由 → 路由分发
"""

import os
import re
import sys
import glob
from typing import Callable
from urllib.parse import urlparse, parse_qs, unquote

from hedera.plugin.base import PluginBase, load_plugin_from_dir, load_skill_from_yaml


class PluginManager:
    """插件管理器。管理插件的加载、卸载、路由。"""

    def __init__(self):
        self._plugins: list[PluginBase] = []
        self._loaded: dict[str, PluginBase] = {}
        self._tool_registry: dict[str, dict] = {}  # name → {fn, description, parameters}
        self._prompt_modifiers: list[str] = []
        self._routes: list[tuple] = []  # (method, compiled_regex, handler, plugin_name)
        self._static_dirs: dict[str, str] = {}  # plugin_name → static_dir

    # ─── 加载 ───

    def load_from_dirs(self, dirs: list[str]):
        """从多个目录加载插件"""
        for d in dirs:
            self._scan_and_load(d)

        # 按 priority 排序
        self._plugins.sort(key=lambda p: p.priority)
        for p in self._plugins:
            print(f"  [OK] 插件: {p}")

    def load_skills(self, skills_dir: str):
        """从 YAML 文件加载技能"""
        if not os.path.isdir(skills_dir):
            return
        for fname in os.listdir(skills_dir):
            if not fname.endswith(".yaml") and not fname.endswith(".yml"):
                continue
            yaml_path = os.path.join(skills_dir, fname)
            skill = load_skill_from_yaml(yaml_path)
            if skill:
                if not skill.name:
                    skill.name = os.path.splitext(fname)[0]
                skill.on_load()
                self._plugins.append(skill)
                self._loaded[skill.name] = skill
                mod = skill.get_system_prompt_modifier()
                if mod:
                    self._prompt_modifiers.append(mod)
                print(f"  [OK] 技能: {skill}")

    def _scan_and_load(self, directory: str):
        if not os.path.isdir(directory):
            return
        for item in os.listdir(directory):
            plugin_dir = os.path.join(directory, item)
            if not os.path.isdir(plugin_dir):
                continue
            if item.startswith("_"):
                continue
            if item in self._loaded:
                continue

            instance = load_plugin_from_dir(plugin_dir)
            if instance:
                if not instance.name:
                    instance.name = item
                instance.on_load()
                self._plugins.append(instance)
                self._loaded[instance.name] = instance
                self._register_tools(instance)
                self._register_routes(instance, plugin_dir)
                mod = instance.get_system_prompt_modifier()
                if mod:
                    self._prompt_modifiers.append(mod)

    def _register_tools(self, plugin: PluginBase):
        tools = plugin.get_tools()
        if not tools:
            return
        # 兼容两种格式：
        #   1) [{"name": "x", "description": "...", "fn": ...}] 列表
        #   2) {"x": {"description": "...", "handler": ...}} 字典
        if isinstance(tools, dict):
            items = []
            for tool_name, tool_def in tools.items():
                if isinstance(tool_def, dict):
                    tool_def.setdefault("name", tool_name)
                    # handler → fn 兼容
                    if "handler" in tool_def and "fn" not in tool_def:
                        tool_def["fn"] = tool_def.pop("handler")
                    items.append(tool_def)
            tools = items
        for t in tools:
            if not isinstance(t, dict):
                continue
            name = t.get("name", "")
            if name:
                self._tool_registry[name] = {
                    "name": name,
                    "description": t.get("description", ""),
                    "fn": t.get("fn"),
                    "parameters": t.get("parameters", {}),
                }

    def _register_routes(self, plugin: PluginBase, plugin_dir: str):
        """收集插件的路由和静态文件目录"""
        # 路由
        routes = plugin.get_routes()
        for route_def in routes:
            if len(route_def) == 3:
                method, path_pattern, handler = route_def
            else:
                continue
            # 将 /api/midi/upload/{name} 转为正则 /api/midi/upload/(?P<name>[^/]+)
            regex_str = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', path_pattern)
            regex_str = f"^{regex_str}$"
            compiled = re.compile(regex_str)
            self._routes.append((method.upper(), compiled, handler, plugin.name))
            print(f"  [ROUTE] {method.upper()} {path_pattern} → {plugin.name}")

        # 静态目录（用目录名做 key，URL 中 /plugins/{dir_name}/static/...）
        static_dir = plugin.get_static_dir()
        if static_dir:
            # 如果是相对路径，相对于插件目录
            if not os.path.isabs(static_dir):
                static_dir = os.path.join(plugin_dir, static_dir)
            if os.path.isdir(static_dir):
                dir_name = os.path.basename(plugin_dir)
                self._static_dirs[dir_name] = static_dir
                print(f"  [STATIC] /plugins/{dir_name}/static/ → {static_dir}")

    # ─── HTTP 路由分发 ───

    def dispatch_http(self, method: str, path: str, headers: dict = None,
                      body: bytes = None, file_data: bytes = None,
                      file_name: str = None) -> tuple | None:
        """
        尝试将 HTTP 请求分发给插件路由。
        返回 (data, status_code) 或 None（无匹配）。
          data 为 dict 则 JSON，为 str/bytes 则原始内容。
        """
        method = method.upper()
        parsed = urlparse(path)
        clean_path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        # 尝试插件路由
        for route_method, regex, handler, plugin_name in self._routes:
            if route_method != method:
                continue
            m = regex.match(clean_path)
            if m:
                context = {
                    "params": m.groupdict(),
                    "query": query,
                    "headers": headers or {},
                    "body": body,
                    "file_data": file_data,
                    "file_name": file_name,
                }
                try:
                    result = handler(context)
                    if result is not None:
                        return result
                except Exception as e:
                    print(f"[PluginRoute] {plugin_name} 处理出错: {e}")
                    return ({"error": str(e)}, 500)

        # 尝试静态文件 /plugins/{name}/static/{filepath}
        static_match = re.match(r'^/plugins/([^/]+)/static/(.+)$', clean_path)
        if static_match:
            plugin_name = static_match.group(1)
            filepath = static_match.group(2)
            if plugin_name in self._static_dirs:
                full_path = os.path.join(self._static_dirs[plugin_name], filepath)
                full_path = os.path.normpath(full_path)
                # 安全检查：防止路径穿越
                if full_path.startswith(self._static_dirs[plugin_name]):
                    if os.path.isfile(full_path):
                        try:
                            with open(full_path, "rb") as f:
                                data = f.read()
                            # 简单 MIME 类型
                            ext = os.path.splitext(filepath)[1].lower()
                            mime_types = {
                                ".html": "text/html",
                                ".js": "application/javascript",
                                ".css": "text/css",
                                ".json": "application/json",
                                ".png": "image/png",
                                ".jpg": "image/jpeg",
                                ".svg": "image/svg+xml",
                            }
                            return (data, 200, mime_types.get(ext, "application/octet-stream"))
                        except Exception as e:
                            return ({"error": str(e)}, 500)

        return None

    # ─── 消息路由 ───

    def route(self, message: str, context: dict = None) -> str | None:
        """
        按优先级尝试匹配插件。
        返回第一个匹配且成功的插件回复，或 None。
        """
        if context is None:
            context = {}

        for plugin in self._plugins:
            score = plugin.match(message)
            if score > 0:
                try:
                    result = plugin.process(message, context)
                    if result is not None:
                        return result
                except Exception as e:
                    print(f"[Plugin] {plugin.name} 处理出错: {e}")
                if plugin.standalone and score >= 1.0:
                    break
        return None

    # ─── 工具 ───

    def get_tool_descriptions(self) -> list[dict]:
        """返回所有插件注册的工具描述（供 LLM function calling）"""
        result = []
        for t in self._tool_registry.values():
            params = t.get("parameters", {})
            # 兼容扁平格式 {"text": {"type": "string"}} → 正确 JSON Schema
            if params and "type" not in params:
                params = {
                    "type": "object",
                    "properties": params,
                    "required": [k for k, v in params.items() if isinstance(v, dict) and v.get("required") is not False],
                }
            result.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": params or {"type": "object", "properties": {}},
                }
            })
        return result

    def call_tool(self, name: str, args: dict = None) -> dict:
        """调用插件注册的工具（沙箱执行）"""
        t = self._tool_registry.get(name)
        if not t:
            return {"success": False, "error": f"未知插件工具: {name}"}
        from hedera.core.sanitizer import run_plugin_safe
        return run_plugin_safe(t["fn"], args or {}, timeout=15)

    def get_prompt_modifier(self) -> str:
        """拼接所有插件的 system prompt 修改"""
        return "\n".join(self._prompt_modifiers)

    # ─── 生命周期 ───

    def unload(self, name: str):
        """卸载指定插件"""
        plugin = self._loaded.pop(name, None)
        if plugin:
            plugin.on_unload()
            self._plugins = [p for p in self._plugins if p.name != name]
            # 清理注册的工具
            self._tool_registry = {k: v for k, v in self._tool_registry.items()
                                   if not k.startswith(f"{name}_")}
            # 清理路由
            self._routes = [r for r in self._routes if r[3] != name]
            # 清理静态目录（key 是目录名，需要遍历删除）
            to_remove = [k for k, v in self._static_dirs.items()
                         if k == name or k.replace("_", " ") == name]
            for k in to_remove:
                self._static_dirs.pop(k, None)

    def unload_all(self):
        for name in list(self._loaded.keys()):
            self.unload(name)

    def list_loaded(self) -> list[dict]:
        return [{"name": p.name, "version": p.version, "author": p.author,
                 "description": p.description, "priority": p.priority}
                for p in self._plugins]

    def is_empty(self) -> bool:
        return len(self._plugins) == 0
