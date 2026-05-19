"""
Hedera 插件基类 — 所有插件继承此接口
"""

import os
import sys
import yaml
from typing import Any


class PluginBase:
    """插件基类。所有插件必须继承此类并实现必要方法。"""

    # 元数据（由 plugin.yaml 覆盖）
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""

    # 匹配规则
    keywords: list[str] = []       # 消息中含这些关键词时触发
    commands: list[str] = []       # 以这些命令前缀开头时触发
    priority: int = 100            # 优先级（越小越先）
    standalone: bool = False       # 是否独占（匹配后不再继续路由）

    def on_load(self, config: dict = None):
        """插件被加载时调用"""
        pass

    def on_unload(self):
        """插件被卸载时调用"""
        pass

    def match(self, message: str) -> float:
        """
        返回匹配度 0.0-1.0。0 = 不匹配。
        默认实现：检查 keywords 和 commands
        """
        score = 0.0
        msg_lower = message.lower()
        for kw in self.keywords:
            if kw.lower() in msg_lower:
                score = max(score, 0.6)
        for cmd in self.commands:
            if message.strip().startswith(cmd):
                score = max(score, 1.0)
        return score

    def process(self, message: str, context: dict = None) -> str | None:
        """
        处理消息。返回回复文本，或 None（不处理交回主路由）。
        """
        return None

    def get_tools(self) -> list[dict]:
        """
        返回额外注册的工具描述列表。
        格式：[{"name": ..., "description": ..., "fn": callable, "parameters": {...}}, ...]
        """
        return []

    def get_system_prompt_modifier(self) -> str | None:
        """返回追加到 system prompt 的文本"""
        return None

    def __str__(self):
        return f"<Plugin {self.name} v{self.version}>"


def load_plugin_from_dir(plugin_dir: str) -> PluginBase | None:
    """从目录加载一个插件"""
    yaml_path = os.path.join(plugin_dir, "plugin.yaml")
    main_path = os.path.join(plugin_dir, "main.py")

    if not os.path.exists(yaml_path) or not os.path.exists(main_path):
        return None

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}
    except Exception:
        return None

    # 动态加载 main.py
    module_name = f"_hedera_plugin_{os.path.basename(plugin_dir)}"
    spec = None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(module_name, main_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"[Plugin] 加载失败 {plugin_dir}: {e}")
        return None

    # 查找插件类
    plugin_cls = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, PluginBase) and attr is not PluginBase:
            plugin_cls = attr
            break

    if plugin_cls is None:
        return None

    instance = plugin_cls()

    # 用 yaml 元数据覆盖类属性
    for key in ["name", "description", "version", "author",
                "keywords", "commands", "priority", "standalone"]:
        if key in meta:
            setattr(instance, key, meta[key])

    return instance
