"""
Hedera 插件管理器
扫描目录 → 加载插件 → 挂载钩子 → 路由请求
"""

import os
import sys
import glob
from typing import Callable

from hedera.plugin.base import PluginBase, load_plugin_from_dir


class PluginManager:
    """插件管理器。管理插件的加载、卸载、路由。"""

    def __init__(self):
        self._plugins: list[PluginBase] = []
        self._loaded: dict[str, PluginBase] = {}
        self._tool_registry: dict[str, dict] = {}  # name → {fn, description, parameters}
        self._prompt_modifiers: list[str] = []

    # ─── 加载 ───

    def load_from_dirs(self, dirs: list[str]):
        """从多个目录加载插件"""
        for d in dirs:
            self._scan_and_load(d)

        # 按 priority 排序
        self._plugins.sort(key=lambda p: p.priority)
        for p in self._plugins:
            print(f"  [OK] 插件: {p}")

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
                mod = instance.get_system_prompt_modifier()
                if mod:
                    self._prompt_modifiers.append(mod)

    def _register_tools(self, plugin: PluginBase):
        tools = plugin.get_tools()
        for t in tools:
            name = t.get("name", "")
            if name:
                self._tool_registry[name] = {
                    "name": name,
                    "description": t.get("description", ""),
                    "fn": t.get("fn"),
                    "parameters": t.get("parameters", {}),
                }

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
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
            }
            for t in self._tool_registry.values()
        ]

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

    def unload_all(self):
        for name in list(self._loaded.keys()):
            self.unload(name)

    def list_loaded(self) -> list[dict]:
        return [{"name": p.name, "version": p.version, "author": p.author,
                 "description": p.description, "priority": p.priority}
                for p in self._plugins]

    def is_empty(self) -> bool:
        return len(self._plugins) == 0
