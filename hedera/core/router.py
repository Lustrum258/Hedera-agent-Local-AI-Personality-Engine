"""
Hedera 核心消息路由器
"""

import os
import sys
import json
import re
import threading
import random
import time
import datetime as dt
import urllib.request
from typing import Any

from hedera.core.memory import build_system_prompt
from hedera.core.memory_store import MemoryStore
from hedera.core.experience import distill_experience_once
from hedera.core.tools import call_tool, get_tool_descriptions, ALL_TOOL_NAMES
from hedera.noise.injector import NoiseInjector
from hedera.noise.slider import SliderEngine
from hedera.plugin.manager import PluginManager

MAX_TOOL_LOOP = 20

_ACTION_KEYWORDS = [
    "查", "看", "找", "读", "写", "改", "删", "复制", "移动", "执行", "运行", "搜",
    "桌面", "文件", "目录", "文件夹", "进程", "任务", "程序", "打开",
    "list", "dir", "read", "write", "search", "create", "make", "run",
    "查看", "浏览", "列出", "读取", "写入", "搜索", "获取", "命令",
]


def _classify_task(message: str) -> str:
    if len(message) < 20:
        return "simple"
    if any(kw in message for kw in ["评价", "分析", "为什么", "怎么看待", "区别"]):
        return "complex"
    if any(kw in message for kw in ["创意", "写一个", "设计", "想象", "假设"]):
        return "creative"
    return "complex"


def _get_strength(task_type: str, config: dict) -> float:
    noise_cfg = config.get("noise", {})
    mapping = {"simple": "simple_task_strength", "complex": "complex_strength", "creative": "creative_strength"}
    return noise_cfg.get(mapping.get(task_type, "complex_strength"), 0.0)


def _call_api(messages: list, config: dict, temperature_override: float = None, tools: list = None, max_retries: int = 1) -> dict:
    """
    调用 LLM API。
    - 工具列表 (`tools`) 一次性构建在 body 中，不存在遗漏
    - 自动重试（指数退避，最多 max_retries 次）
    - 指标记录
    """
    from hedera.core.logger import METRICS, Timer
    _timer = Timer()
    model_cfg = config.get("model", {})
    api_key = model_cfg.get("api_key", "") or os.environ.get(model_cfg.get("api_key_env", "HEDERA_API_KEY"), "")
    temp = temperature_override if temperature_override is not None else model_cfg.get("temperature", 0.7)
    endpoint = model_cfg.get("endpoint", "https://api.deepseek.com/chat/completions")
    model_name = model_cfg.get("name", "deepseek-chat")

    # 一次性构建 body（tools 始终包含，空 list 传给 API 也没问题）
    body_payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temp,
        "max_tokens": model_cfg.get("max_tokens", 4096),
    }
    if tools:
        body_payload["tools"] = tools
    body = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")

    last_exception = None
    for attempt in range(1, min(max_retries, 2) + 1):  # 最多重试 1 次（共 2 次尝试）
        try:
            r = urllib.request.Request(endpoint, data=body, headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }, method="POST")
            resp = urllib.request.urlopen(r, timeout=120)
            data = json.loads(resp.read().decode())
            METRICS.record_api_call(success=True, latency=_timer.elapsed())
            # 验证响应格式
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]
            else:
                raise ValueError(f"API 返回格式异常: {list(data.keys())}")
        except Exception as e:
            last_exception = e
            METRICS.record_api_call(success=False, latency=_timer.elapsed())
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)  # 指数退避: 2s, 4s, 8s... 上限 30s
                _timer.reset()
                time.sleep(wait)

    return {"content": f"[Hedera API Error] {last_exception}", "tool_calls": None}


def _try_parse_xml_toolcall(content: str) -> list | None:
    results = []
    for m in re.finditer(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', content, re.DOTALL):
        name = m.group(1)
        body = m.group(2)
        params = {}
        for p in re.finditer(r'<parameter\s+name="([^"]+)"[^>]*>([^<]*)</parameter>', body):
            params[p.group(1)] = p.group(2)
        if name and params:
            results.append({
                "id": f"call_xml_{hash(content) % 10000}",
                "function": {"name": name, "arguments": json.dumps(params, ensure_ascii=False)},
            })
    return results if results else None


def _build_tool_prompt() -> str:
    """
    动态构建工具提示段，自动跟随注册的工具列表。
    新增工具 → 自动出现在提示中，不需手改。
    """
    from hedera.core.tools import _TOOLS
    lines = ["\n\n## 环境与工具"]

    # 环境信息
    import platform
    import os as _os
    cwd = os.getcwd() if hasattr(os, 'getcwd') else _os.getcwd()
    lines.append(f"\n### 运行环境")
    lines.append(f"- 操作系统: {platform.system()} {platform.release()}")
    lines.append(f"- Python: {platform.python_version()}")
    lines.append(f"- 当前目录: {cwd}")

    # 工具清单（自动从注册表读取）
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
                parts.append(f"{pname}{required_mark}{default_str}")
            param_str = " → ".join(parts)
        if param_str:
            lines.append(f"- `{name}`: {desc}  参数: {param_str}")
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


# ─── 自省系统 ───

_reflection_log = []
_reflection_details = []  # 完整维度详情
_experience_log = []
_last_distill_time = 0  # 上次蒸馏时间戳，用于冷却
_shutdown_event = threading.Event()


def _reflect_loop(config: dict, db_dir: str):
    if _shutdown_event.wait(timeout=60):  # 初始等待60s，可被 shutdown 提前中断
        return
    store = MemoryStore(db_dir, session_id="_reflection")
    counter = 0
    while not _shutdown_event.is_set():
        if _shutdown_event.wait(timeout=5 * 60):
            break
        try:
            history = store.get_recent_history(limit=100)
            user_count = sum(1 for m in history if m["role"] == "user")
            if user_count - counter >= 3:
                counter = user_count
                _do_reflection(history, config, store)
        except Exception:
            pass


def _get_reflection_quality(dims: dict, content: str) -> int:
    """评估自省记录的置信度（1-10），低于4的跳过蒸馏"""
    if not content or len(content.strip()) < 20:
        return 1
    # 检查是否重复或空洞
    nonempty = sum(1 for v in dims.values() if v and len(v) > 10)
    if nonempty < 2:
        return 2
    # 检查是否在复读自省问题
    lines = content.strip().split("\n")
    unique_lines = len(set(l.strip() for l in lines if l.strip()))
    total_lines = len([l for l in lines if l.strip()])
    if total_lines > 3 and unique_lines / total_lines < 0.4:
        return 2  # 大量重复行
    # 有实质内容的维度越多分越高
    score = 3 + nonempty * 2
    # 有盲区识别加分
    if dims.get("blindspot"):
        score += 1
    return min(score, 10)


def _do_reflection(history: list, config: dict, store: MemoryStore):
    global _last_distill_time
    # 冷却检查：蒸馏后10分钟内不自省
    if time.time() - _last_distill_time < 600:
        store.save_message("system", "[自省] 跳过：蒸馏冷却中", "auto_reflect")
        return

    config_local = config
    pairs = []
    for i in range(len(history) - 1, -1, -1):
        if history[i]["role"] == "assistant" and i > 0 and history[i - 1]["role"] == "user":
            pairs.insert(0, {
                "user": history[i - 1]["content"][:200],
                "assistant": history[i]["content"][:200],
            })
        if len(pairs) >= 5:
            break

    context_summary = "（无近期对话）"
    if pairs:
        lines = [f"[轮{i+1}] 用户: {p['user'][:150]}\n  冬青: {p['assistant'][:150]}" for i, p in enumerate(pairs)]
        context_summary = "\n".join(lines)

    reflection_prompt = (
        f"## 对话复盘指令\n最近对话摘要：\n{context_summary}\n\n"
        f"请按4个维度逐一产出洞察：\n"
        f"<!-- dim:1 -->【学到了什么】\n"
        f"<!-- dim:2 -->【哪里需要改进】\n"
        f"<!-- dim:3 -->【可提炼的原则】\n"
        f"<!-- dim:4 -->【盲区与假设修正】\n"
        f"每个维度不超过120字。诚实、不美化。"
    )

    sys_prompt = build_system_prompt(config)
    msgs = [
        {"role": "system", "content": f"{sys_prompt}\n\n现在是内部复盘，不是回答用户。诚实。"},
        {"role": "user", "content": reflection_prompt},
    ]
    result = _call_api(msgs, config_local, temperature_override=0.4)
    content = result.get("content", "")

    dims = {"learned": "", "improve": "", "principle": "", "blindspot": ""}
    for marker, key in [
        ("<!-- dim:1 -->", "learned"),
        ("<!-- dim:2 -->", "improve"),
        ("<!-- dim:3 -->", "principle"),
        ("<!-- dim:4 -->", "blindspot"),
    ]:
        m = re.search(rf"{re.escape(marker)}\s*(.*?)(?=<!-- dim:|\Z)", content, re.DOTALL)
        if m:
            dims[key] = m.group(1).strip()

    quality = _get_reflection_quality(dims, content)

    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    summary = f"【{now}】[置信度:{quality}/10]"
    if dims.get("learned"):
        store.save_long_term("reflection_learned", dims["learned"][:300], "reflection", quality)
        summary += f"\n📖 {dims['learned'][:150]}"
    if dims.get("improve"):
        store.save_long_term("reflection_improve", dims["improve"][:300], "reflection", quality)
        summary += f"\n🔧 {dims['improve'][:150]}"
    if dims.get("principle"):
        store.save_long_term(f"principle_{int(time.time())}", dims["principle"][:300], "principle", quality)
        summary += f"\n📐 {dims['principle'][:150]}"
    if dims.get("blindspot"):
        store.save_long_term(f"blindspot_{int(time.time())}", dims["blindspot"][:300], "blindspot", quality)
        summary += f"\n⚠️ {dims['blindspot'][:150]}"

    _reflection_log.append(summary)
    _reflection_details.append({
        "time": now,
        "quality": quality,
        "dims": {k: v[:500] for k, v in dims.items() if v},
        "summary": summary,
    })
    # 只保留最近 50 条
    if len(_reflection_details) > 50:
        _reflection_details[:] = _reflection_details[-50:]
    store.save_message("system", f"[自省] {summary}", "auto_reflect")
    # 触发经验蒸馏线程（如果还没启动）
    _ensure_experience_thread(config, db_dir)


# ─── 状态 ───

_noise = NoiseInjector()
_slider = SliderEngine()
_last_system_prompt = ""
_store = None
_reflection_thread = None
_experience_thread = None
_plugin_manager: PluginManager | None = None

# 会话状态管理（多 session 支持）
_session_stores: dict[str, 'MemoryStore'] = {}  # session_id → MemoryStore
_session_db_dir = None


def _ensure_experience_thread(config: dict, db_dir: str):
    """确保蒸馏线程已启动"""
    global _experience_thread
    if _experience_thread is not None and _experience_thread.is_alive():
        return
    _experience_thread = threading.Thread(
        target=_experience_loop, args=(config, db_dir), daemon=True
    )
    _experience_thread.start()


def _experience_loop(config: dict, db_dir: str):
    """经验蒸馏主循环 — 每 30 分钟检查一次"""
    global _last_distill_time
    store = MemoryStore(db_dir, session_id="_experience")
    failure_count = 0
    while not _shutdown_event.is_set():
        if _shutdown_event.wait(timeout=30 * 60):
            break  # 30分钟
        try:
            _last_distill_time = time.time()
            rules = distill_experience_once(store, config, db_dir)
            if rules:
                _experience_log.append({
                    "time": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "rules": rules,
                })
                store.save_message(
                    "system",
                    f"[蒸馏] 提炼 {len(rules)} 条经验准则",
                    "experience",
                )
            failure_count = 0  # 成功一次重置计数
        except Exception as e:
            failure_count += 1
            store.save_message(
                "system",
                f"[蒸馏] 失败 #{failure_count}: {str(e)[:100]}",
                "experience",
            )
            if failure_count >= 3:
                store.save_message(
                    "system",
                    "[蒸馏] 连续失败3次，暂停蒸馏",
                    "experience",
                )
                time.sleep(60 * 60)  # 暂停1小时


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


def ensure_store(config: dict, session_id: str = None) -> 'MemoryStore':
    """
    获取或创建指定会话的 MemoryStore。
    如果 session_id 为 None，使用默认的全局会话。
    """
    global _store, _session_db_dir, _session_stores

    data_dir = config.get("__hedera__", {}).get("config_dir", os.getcwd())
    identity_cfg = config.get("identity", {})
    mem_path = identity_cfg.get("memory", "data/MEMORY.md")
    if not os.path.isabs(mem_path):
        mem_path = os.path.join(data_dir, os.path.dirname(mem_path))
    db_dir = os.path.dirname(os.path.abspath(mem_path))
    # 修复：如果 db_dir 结尾不是 data（被 os.path.dirname 吃掉了一层），补上
    need_data_dir = os.path.join(data_dir, "data")
    if os.path.dirname(os.path.abspath(mem_path)) == data_dir and os.path.isdir(need_data_dir):
        db_dir = need_data_dir
    _session_db_dir = db_dir

    # 没有 session_id → 使用固定默认会话（跨重启稳定）
    if session_id is None:
        if _store is None:
            _store = MemoryStore(db_dir, session_id="_default")
        return _store

    # 显式 session_id → 多会话模式
    if session_id not in _session_stores:
        _session_stores[session_id] = MemoryStore(db_dir, session_id=session_id)
    return _session_stores[session_id]


# ─── 会话管理 API ───

def list_sessions() -> list[dict]:
    """列出所有会话"""
    store = ensure_store(config={}, session_id="_admin")
    # 重建一个干净的 store 只是为了查询
    from hedera.core.memory_store import MemoryStore
    if _session_db_dir:
        q = MemoryStore(_session_db_dir, session_id="_admin")
        return q.list_sessions()
    return []


def create_session(session_id: str = None, title: str = "") -> dict:
    """创建新会话"""
    from hedera.core.memory_store import MemoryStore
    if not _session_db_dir:
        return {"error": "no db dir"}
    q = MemoryStore(_session_db_dir, session_id="_admin")
    sid = q.create_session(session_id, title)
    return {"session_id": sid, "title": title}


def get_session_messages(session_id: str, limit: int = 100) -> list[dict]:
    """获取指定会话的消息"""
    from hedera.core.memory_store import MemoryStore
    if not _session_db_dir:
        return []
    q = MemoryStore(_session_db_dir, session_id="_admin")
    return q.get_session_messages(session_id, limit)


def delete_session(session_id: str) -> dict:
    """删除会话"""
    from hedera.core.memory_store import MemoryStore
    if not _session_db_dir:
        return {"error": "no db dir"}
    q = MemoryStore(_session_db_dir, session_id="_admin")
    q.delete_session(session_id)
    # 清理缓存
    if session_id in _session_stores:
        del _session_stores[session_id]
    return {"status": "deleted", "session_id": session_id}


def process_message(message: str, config: dict, session_id: str = None) -> tuple:
    """
    处理消息，返回 (response_content, session_id, files)。
    files 为该轮生成的下载文件列表。
    支持多会话：每请求使用独立的噪声/滑块实例，无全局锁。
    """
    global _last_system_prompt, _store, _reflection_thread, _plugin_manager, _session_stores
    # 每请求独立实例，避免全局状态竞争
    noise = NoiseInjector()
    slider = SliderEngine()
    _pending_files = []  # 暂存本轮生成的文件

    # 获取/创建会话存储
    store = ensure_store(config, session_id)
    actual_session_id = store.session_id

    # ── 按会话固定人格 ──
    # 如果该会话绑定了 personality profile，临时切换 config
    saved_soul = None
    saved_name = None
    try:
        sess_info = store.get_session_info(actual_session_id)
        sess_profile = sess_info.get("profile", "") if sess_info else ""
        if sess_profile:
            # 找到对应的人格文件
            config_path = config.get("__hedera__", {}).get("config_path", "")
            if config_path:
                project_dir = os.path.dirname(os.path.abspath(config_path))
                profiles_dir = os.path.join(project_dir, "profiles")
                profile_path = os.path.join(profiles_dir, sess_profile)
                if os.path.isfile(profile_path):
                    saved_soul = config.get("identity", {}).get("soul", "")
                    saved_name = config.get("identity", {}).get("name", "")
                    config["identity"]["soul"] = profile_path
                    pname = os.path.splitext(sess_profile)[0]
                    if "-" in pname:
                        pname = pname.split("-")[0]
                    config["identity"]["name"] = pname
    except Exception:
        pass

    # 初始化插件
    if _plugin_manager is None:
        _init_plugins(config)

    # 插件路由（独立处理 — 不经过 LLM）
    if _plugin_manager and not _plugin_manager.is_empty():
        plugin_reply = _plugin_manager.route(message, {"config": config})
        if plugin_reply:
            return plugin_reply

    # 确保 db_dir 已知
    data_dir = config.get("__hedera__", {}).get("config_dir", os.getcwd())
    identity_cfg = config.get("identity", {})
    mem_path = identity_cfg.get("memory", "data/MEMORY.md")
    if not os.path.isabs(mem_path):
        mem_path = os.path.join(data_dir, os.path.dirname(mem_path))
    db_dir = os.path.dirname(os.path.abspath(mem_path))
    # 修复：如果 db_dir 结尾不是 data（被 os.path.dirname 吃掉了一层），补上
    need_data_dir = os.path.join(data_dir, "data")
    if os.path.dirname(os.path.abspath(mem_path)) == data_dir and os.path.isdir(need_data_dir):
        db_dir = need_data_dir
    _session_db_dir = db_dir

    # 启动自省线程
    if _reflection_thread is None:
        _reflection_thread = threading.Thread(
            target=_reflect_loop, args=(config, db_dir), daemon=True
        )
        _reflection_thread.start()

    task_type = _classify_task(message)
    strength = _get_strength(task_type, config)

    history = store.get_recent_history(limit=100)

    # 系统提示
    system_base = build_system_prompt(config)
    if system_base != _last_system_prompt:
        _last_system_prompt = system_base
    slider_mod = slider.get_system_prompt_modifier()
    plugin_mod = _get_plugin_prompt_modifier()
    system_text = system_base
    if slider_mod:
        system_text += f"\n{slider_mod}"
    if plugin_mod:
        system_text += f"\n{plugin_mod}"
    system_text += _build_tool_prompt()

    # 检测工具需求
    needs_tool = any(kw in message for kw in _ACTION_KEYWORDS)
    user_message = message

    # 构建消息列表
    msgs = [{"role": "system", "content": system_text}]
    for h in history:
        msgs.append({"role": h["role"], "content": h["content"]})

    # 噪声处理
    if task_type != "simple" and config.get("noise", {}).get("enabled", True):
        if strength < 0.1:
            noise_type = "gaussian"
        elif strength < 0.2:
            noise_type = "poisson"
        else:
            noise_type = "impulse"
        noised_msg, jumps = noise.inject(user_message, strength, noise_type=noise_type)
        msgs.append({"role": "user", "content": noised_msg})
        if jumps:
            store.save_noise_jumps(jumps)
            for j in jumps:
                if j["type"] == "poisson":
                    slider.adjust("drive", -0.08)
                elif j["type"] == "impulse":
                    slider.adjust("thinking", 0.1)
                    slider.adjust("drive", -0.15)
            store.save_slider_state(slider.state.to_dict())
    else:
        msgs.append({"role": "user", "content": user_message})

    if needs_tool:
        msgs.append({
            "role": "user",
            "content": "（先调合适的工具获取信息，再回答。工具出错就换方式。）"
        })

    # 工具调用循环（合并核心工具 + 插件工具）
    core_tools = get_tool_descriptions()
    merged_tools = _merge_tools(core_tools)
    tool_loop_count = 0
    final_content = ""
    last_exception = None
    content = ""

    while tool_loop_count < MAX_TOOL_LOOP:
        tool_loop_count += 1
        result = _call_api(msgs, config, tools=merged_tools)

        if not result or not isinstance(result, dict):
            last_exception = "API返回格式异常"
            break

        content = result.get("content") or ""
        tool_calls = result.get("tool_calls")

        if not tool_calls:
            xml_tools = _try_parse_xml_toolcall(content)
            if xml_tools:
                tool_calls = xml_tools
                content = ""

        if not tool_calls:
            final_content = content
            break

        assistant_msg = {"role": "assistant", "content": content}
        tc_list = []
        for tc in tool_calls:
            tc_list.append({
                "id": tc.get("id", f"call_{tool_loop_count}"),
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            })
        assistant_msg["tool_calls"] = tc_list
        msgs.append(assistant_msg)

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                func_args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                func_args = {}

            # 先查核心工具，再查插件工具
            tool_result = call_tool(func_name, func_args)

            # 仅在核心工具"不存在"时才 fallback 到插件层
            # （而非在执行失败时也 fallback — 否则会丢失真实错误信息）
            if (not tool_result.get("success")
                and "未知工具" in tool_result.get("error", "")
                and _plugin_manager is not None):
                try:
                    plugin_result = _plugin_manager.call_tool(func_name, func_args)
                    if plugin_result.get("success"):
                        tool_result = plugin_result
                except Exception:
                    pass

            tool_response = json.dumps(tool_result, ensure_ascii=False, default=str)
            if len(tool_response) > 8000:
                tool_response = tool_response[:7500] + "\n...（结果过长已截断）"

            msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{tool_loop_count}"),
                "content": tool_response,
            })

            # 每调一个工具存一次检查点 → 崩了也能恢复到这个进度
            try:
                store.save_checkpoint({
                    "loop": tool_loop_count,
                    "tool": func_name,
                    "args": func_args,
                    "result": tool_result.get("success", False),
                    "time": time.time(),
                })
            except Exception:
                pass

            # 记录 create_file / send_file / 含 download_url 的插件工具生成的文件
            if tool_result.get("success") and tool_result.get("download_url"):
                try:
                    _pending_files.append({
                        "filename": tool_result.get("file", func_args.get("filename", "file")),
                        "url": tool_result.get("download_url", ""),
                        "size": tool_result.get("size", 0),
                    })
                except Exception:
                    pass
            elif func_name in ("create_file", "send_file") and tool_result.get("success"):
                try:
                    _pending_files.append({
                        "filename": tool_result.get("file", func_args.get("filename", "file")),
                        "url": tool_result.get("url", ""),
                        "size": tool_result.get("size", 0),
                    })
                except Exception:
                    pass

    if not final_content:
        if content and "<invoke" not in content and "</invoke>" not in content:
            final_content = content
        elif last_exception:
            final_content = f"[Hedera] 处理出错: {last_exception}"
        elif tool_loop_count >= MAX_TOOL_LOOP:
            msgs.append({
                "role": "user",
                "content": "工具调用结束。根据所有返回结果直接给用户完整回答，不再调任何工具。"
            })
            final_result = _call_api(msgs, config, tools=[])
            final_content = final_result.get("content", "[Hedera] 处理完成")
        else:
            final_content = "[Hedera] 处理完成"

    # 后处理自检
    if task_type in ("complex", "creative") and strength > 0.1:
        check_prompt = (
            f"快速自检：有没有遗漏关键角度？\n用户说：{message}\n回答：{final_content[:500]}\n"
            f"没问题回复 OK，想补充输出修正版（50字内）。"
        )
        check_msgs = [{"role": "system", "content": system_text}, {"role": "user", "content": check_prompt}]
        check_result_msg = _call_api(check_msgs, config, temperature_override=0.3)
        check_result = check_result_msg.get("content", "OK")

        if check_result.strip() != "OK" and len(check_result) > 3:
            merge_prompt = (
                f"整合两个版本为一个连贯回答：\n初版：{final_content[:800]}\n"
                f"修正：{check_result}\n输出最终版。"
            )
            merge_msgs = [{"role": "system", "content": system_text}, {"role": "user", "content": merge_prompt}]
            merge_result = _call_api(merge_msgs, config)
            final_content = merge_result.get("content", final_content)

    # 先保存用户消息（如果后面崩了至少用户说了什么还在）
    store.save_message("user", message, task_type)
    msg_rowid = store.save_message("assistant", final_content, task_type, return_rowid=True)

    # 把本轮生成的文件关联到这条消息
    new_files = []
    for pf in _pending_files:
        store.save_file_link(
            filename=pf["filename"],
            url=pf["url"],
            size=pf["size"],
            message_rowid=msg_rowid,
        )
        new_files.append(pf)

    return final_content, actual_session_id, new_files


def get_reflection_log():
    """暴露自省日志（供 HTTP API 调用）"""
    return _reflection_log


def get_reflection_details():
    """暴露自省完整维度（供 HTTP API 调用）"""
    return _reflection_details


def get_experience_log():
    """暴露蒸馏日志（供 HTTP API 调用）"""
    return _experience_log


def shutdown():
    """
    优雅关闭后台线程。
    设置退出信号 → 自省和蒸馏线程在下次 sleep 醒来后自动退出。
    """
    global _shutdown_event
    _shutdown_event.set()


def reset_state():
    global _noise, _slider, _store, _last_system_prompt, _session_stores
    _noise = NoiseInjector()
    _slider = SliderEngine()
    _store = None
    _last_system_prompt = ""
    _session_stores = {}
