"""
Hedera 工具提示构建与插件管理
"""

import os
import platform

from hedera.plugin.manager import PluginManager


_plugin_manager: PluginManager | None = None


def _init_plugins(config: dict):
    """初始化插件系统"""
    global _plugin_manager
    pm = PluginManager()

    # 内建插件目录
    builtin_dir = os.path.join(os.path.dirname(__file__), "..", "plugin", "builtin")
    dirs_to_scan = [builtin_dir]

    # 用户插件目录
    data_dir = config.get("__hedera__", {}).get("config_dir", os.getcwd())
    user_plugin_dir = os.path.join(data_dir, "plugins")
    if os.path.isdir(user_plugin_dir):
        dirs_to_scan.append(user_plugin_dir)

    # 额外插件目录
    plugin_cfg = config.get("plugin", {})
    if plugin_cfg.get("load_examples", False):
        examples_dir = os.path.join(os.path.dirname(__file__), "..", "plugin", "examples")
        dirs_to_scan.append(examples_dir)

    pm.load_from_dirs(dirs_to_scan)

    from hedera.core.logger import info as _log_info
    if pm.is_empty():
        _log_info("PluginManager", loaded=False, count=0)
    else:
        _log_info("PluginManager", loaded=True, count=len(pm._plugins))

    _plugin_manager = pm


def _build_tool_prompt() -> str:
    """
    动态构建工具提示段，自动跟随注册的工具列表。
    新增工具 → 自动出现在提示中，不需手改。
    """
    from hedera.core.tools import _TOOLS
    lines = ["\n\n## 环境与工具"]

    # 环境信息
    cwd = os.getcwd()
    lines.append(f"\n### 运行环境")
    lines.append(f"- 操作系统: {platform.system()} {platform.release()}")
    lines.append(f"- Python: {platform.python_version()}")
    lines.append(f"- 当前目录: {cwd}")

    # 工具清单（自动从注册表读取，含参数描述）
    lines.append(f"\n### 可用工具（共{len(_TOOLS)}个）")
    for t in _TOOLS.values():
        name = t["name"]
        desc = t["description"]
        params = t.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])
        param_str = ""
        if props:
            parts = []
            for pname, pinfo in props.items():
                required_mark = " (必填)" if pname in required else ""
                default_val = pinfo.get("default", "")
                default_str = f" 默认={default_val}" if default_val != "" else ""
                # 取参数描述的第一句（截断到50字）
                pdesc = pinfo.get("description", "")
                if pdesc:
                    pdesc = pdesc.split(".")[0].split("。")[0][:50]
                    parts.append(f"{pname}{required_mark}{default_str}: {pdesc}")
                else:
                    parts.append(f"{pname}{required_mark}{default_str}")
            param_str = "\n  - ".join(parts)
        if param_str:
            lines.append(f"- `{name}`: {desc}\n  - {param_str}")
        else:
            lines.append(f"- `{name}`: {desc}")

    # 规则
    lines.append("""
### 工具使用规则
1. 用户要求操作 → 先调工具，再根据结果回答
2. 一个方案走不通自动换另一个
3. 纯聊天讨论 → 不调工具，直接回答
4. 信息不够就自己查，不追问用户
5. 工具结果足够就直接回答，不需要再确认
6. 新增的工具会自动出现在以上清单中 → 直接使用即可""")

    return "\n".join(lines)


def _merge_tools(core_tools: list[dict]) -> list[dict]:
    """合并核心工具和插件工具"""
    global _plugin_manager
    if _plugin_manager is None:
        return core_tools
    plugin_tools = _plugin_manager.get_tool_descriptions()
    return core_tools + plugin_tools


def _get_plugin_prompt_modifier() -> str:
    global _plugin_manager
    if _plugin_manager is None:
        return ""
    return _plugin_manager.get_prompt_modifier()
