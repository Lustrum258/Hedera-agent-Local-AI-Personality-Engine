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

    def get_routes(self) -> list[tuple]:
        """
        返回插件注册的 HTTP 路由列表。
        格式：[(method, path_pattern, handler), ...]
          method: "GET" / "POST" / "DELETE" 等
          path_pattern: 如 "/api/midi/upload" 或 "/api/midi/{name}"
            {name} 会匹配到 context["params"]["name"]
          handler: async_or_sync (context) -> response
            context = {"params": dict, "query": dict, "headers": dict,
                        "body": bytes, "file_data": bytes|None, "file_name": str|None}
            response = (data, code)
              data 为 dict 则发 JSON，为 bytes/str 则发原始内容
        """
        return []

    def get_static_dir(self) -> str | None:
        """
        返回插件的静态文件目录路径。
        目录中的文件会通过 /plugins/<name>/static/<filename> 提供访问。
        """
        return None

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


class SkillPlugin(PluginBase):
    """
    轻量级技能插件 — 由 YAML 定义，无需 main.py。
    通过 prompt 注入实现技能功能。
    """

    def __init__(self, skill_data: dict):
        self.name = skill_data.get("name", "")
        self.description = skill_data.get("description", "")
        self.keywords = skill_data.get("keywords", [])
        self.commands = skill_data.get("commands", [])
        self.priority = 50  # 技能优先级高于普通插件
        self.standalone = False
        self._prompt = skill_data.get("prompt", "")

    def process(self, message: str, context: dict = None) -> str | None:
        """
        技能不直接处理消息，而是通过 system_prompt_modifier 注入 prompt。
        返回 None 让主路由继续处理（LLM 会看到注入的 prompt）。
        """
        return None

    def get_system_prompt_modifier(self) -> str | None:
        """将技能 prompt 注入系统提示"""
        if self._prompt:
            return f"\n【当前技能: {self.name}】\n{self._prompt}"
        return None


def load_skill_from_yaml(yaml_path: str) -> SkillPlugin | None:
    """从 YAML 文件加载一个技能"""
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not data.get("name"):
            return None
        return SkillPlugin(data)
    except Exception as e:
        print(f"[Skill] 加载失败 {yaml_path}: {e}")
        return None
