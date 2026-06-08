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
from typing import Any

from hedera.core.memory import build_system_prompt
from hedera.core.memory_store import MemoryStore
from hedera.core.experience import distill_experience_once
from hedera.core.tools import call_tool, get_tool_descriptions, ALL_TOOL_NAMES
from hedera.core.context_manager import build_context_messages, estimate_max_context
from hedera.noise.injector import NoiseInjector
from hedera.noise.slider import SliderEngine
from hedera.plugin.manager import PluginManager
from hedera.training.signal import SignalManager

MAX_TOOL_LOOP = 20

_ACTION_KEYWORDS = [
    # 文件/目录操作（需要较长短语避免误触发）
    "读取文件", "写入文件", "删除文件", "创建文件", "复制文件",
    "查看文件", "查看目录", "列出文件", "列出目录", "搜索文件",
    "file", "directory", "folder",
    # 进程/系统
    "执行命令", "运行命令", "运行脚本", "运行程序",
    "进程列表", "任务管理", "系统信息",
    "exec_shell", "run_python",
    # 网络
    "搜索网页", "抓取网页", "下载文件", "网页内容",
    "web_search", "web_fetch",
    # 编码相关（只有明确涉及代码才触发）
    "写代码", "改代码", "看代码", "读代码", "写程序",
    "代码审查", "code review", "调试代码",
    "git status", "git commit", "git push", "git diff",
    "pip install", "npm install",
    "grep_files", "find_definition", "edit_file",
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


_last_api_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
_usage_lock = threading.Lock()


def _call_api(messages: list, config: dict, temperature_override: float = None, tools: list = None, max_retries: int = 2, max_tokens_override: int = 0) -> dict:
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

    # 简单对话限制 max_tokens，减少推理模型的推理开销
    default_max = model_cfg.get("max_tokens", 4096)
    if max_tokens_override:
        effective_max = max_tokens_override
    elif len(messages) <= 4:  # system + 少量消息 = 简单对话
        effective_max = min(default_max, 2048)
    else:
        effective_max = default_max

    # 一次性构建 body（tools 始终包含，空 list 传给 API 也没问题）
    body_payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temp,
        "max_tokens": effective_max,
    }
    if tools:
        body_payload["tools"] = tools
    last_exception = None
    for attempt in range(1, max_retries + 1):  # 重试 max_retries 次
        try:
            import requests as _requests
            resp = _requests.post(
                endpoint,
                json=body_payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=300,
            )
            data = resp.json()
            METRICS.record_api_call(success=True, latency=_timer.elapsed())
            # 捕获 API 返回的 token 用量
            if "usage" in data and isinstance(data["usage"], dict):
                with _usage_lock:
                    _last_api_usage.update(data["usage"])
            # 提取 API 错误信息
            if "error" in data:
                err = data["error"]
                if isinstance(err, dict):
                    err_msg = err.get("message", "") or err.get("msg", "") or str(err)
                else:
                    err_msg = str(err)
                raise ValueError(f"API 错误 ({resp.status_code}): {err_msg}")
            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0]["message"]
                # 防御：某些 API 返回 message 为字符串而非 dict
                if isinstance(msg, str):
                    msg = {"content": msg, "tool_calls": None}
                return msg
            else:
                raise ValueError(f"API 返回格式异常: {list(data.keys())}")
        except Exception as e:
            last_exception = e
            METRICS.record_api_call(success=False, latency=_timer.elapsed())
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
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


# ─── 自省系统 ───

_reflection_log = []
_reflection_details = []  # 完整维度详情
_experience_log = []
_last_distill_time = 0  # 上次蒸馏时间戳，用于冷却
_shutdown_event = threading.Event()

# 自提问无回答计数器
_proactive_unanswered = 0
_PROACTIVE_MAX_UNANSWERED = 3

# 工具调用进度存储（供前端轮询）
_tool_progress: dict[str, dict] = {}
_tool_progress_lock = threading.Lock()


def set_tool_progress(req_id: str, name: str, args: dict, result: dict):
    """记录一次工具调用进度"""
    with _tool_progress_lock:
        _tool_progress[req_id] = {
            "name": name,
            "args": dict(args) if args else {},
            "status": "success" if result.get("success") else "error",
            "error": result.get("error", "")[:100] if not result.get("success") else "",
        }


def get_tool_progress(req_id: str) -> dict:
    """获取工具调用进度"""
    with _tool_progress_lock:
        return _tool_progress.get(req_id, {})


def clear_tool_progress(req_id: str):
    """清除进度记录"""
    with _tool_progress_lock:
        _tool_progress.pop(req_id, None)


def _check_user_interrupt(store, original_message: str) -> bool:
    """检查用户是否有新消息（插嘴），用于中断长任务"""
    try:
        history = store.get_recent_history(limit=5)
        if not history:
            return False
        # 最近一条消息如果是用户消息且不是原始消息，说明用户插嘴了
        last = history[-1]
        if last.get("role") == "user" and last.get("content", "") != original_message:
            return True
    except Exception:
        pass
    return False


def _reflect_loop(config: dict, db_dir: str):
    if _shutdown_event.wait(timeout=60):  # 初始等待60s，可被 shutdown 提前中断
        return
    reflection_store = MemoryStore(db_dir, session_id="_reflection")
    counter = 0
    _SYSTEM_SESSIONS = {"_reflection", "_experience", "_api", "_admin", "_cross_session_prompt", "_default"}

    while not _shutdown_event.is_set():
        if _shutdown_event.wait(timeout=5 * 60):
            break
        try:
            # 从最近的用户会话读取历史（而非 _reflection session）
            all_sessions = reflection_store.list_sessions()
            user_sessions = [s for s in all_sessions if s.get("session_id", "") not in _SYSTEM_SESSIONS]
            if not user_sessions:
                continue
            # 取最近活跃的会话
            recent_sid = user_sessions[0].get("session_id", "")
            if not recent_sid:
                continue
            user_store = MemoryStore(db_dir, session_id=recent_sid)
            history = user_store.get_recent_history(limit=100)
            user_count = sum(1 for m in history if m["role"] == "user")
            if user_count - counter >= 3:
                counter = user_count
                _do_reflection(history, config, reflection_store)
        except Exception:
            pass


def _last_proactive_was_answered(pstore) -> bool:
    """检查目标会话中，最近一条 proactive 消息之后是否有用户回复"""
    try:
        history = pstore.get_recent_history(limit=50)
        last_proactive_idx = None
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("task_type") == "proactive":
                last_proactive_idx = i
                break
        if last_proactive_idx is None:
            return True  # 没有历史 proactive 消息，算已回答（初始状态）
        # 检查 proactive 之后是否有 user 消息
        for i in range(last_proactive_idx + 1, len(history)):
            if history[i]["role"] == "user":
                return True
        return False
    except Exception:
        return True  # 查不到就保守归零


def _deliver_proactive_message(reflection_store: MemoryStore, db_dir: str, text: str):
    """将主动提问写入最近活跃的会话（含无回答限制）"""
    global _proactive_unanswered
    try:
        all_sessions = reflection_store.list_sessions()
        if all_sessions:
            sorted_sessions = sorted(
                all_sessions,
                key=lambda s: s.get("updated_at", "") or "",
                reverse=True
            )
            target_session = sorted_sessions[0]["session_id"]
            pstore = MemoryStore(db_dir, session_id=target_session)
        else:
            pstore = reflection_store

        # 检查上次提问是否被回答
        if _last_proactive_was_answered(pstore):
            _proactive_unanswered = 0
        else:
            _proactive_unanswered += 1

        # 连续无回答达到上限 → 跳过，不再提问
        if _proactive_unanswered >= _PROACTIVE_MAX_UNANSWERED:
            from hedera.core.logger import info as _li
            _li("Proactive skipped: 3 unanswered", count=_proactive_unanswered)
            reflection_store.save_message(
                "system",
                f"[自提问] 跳过：连续{_proactive_unanswered}次无回答",
                "proactive_skip",
            )
            return

        pstore.save_message("assistant", text, "proactive")
    except Exception:
        reflection_store.save_message("assistant", text, "proactive")


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
    if len(_reflection_log) > 50:
        _reflection_log[:] = _reflection_log[-50:]
    store.save_message("system", f"[自省] {summary}", "auto_reflect")
    # 触发经验蒸馏线程（如果还没启动）
    _db_dir = os.path.dirname(store.db_path)
    _ensure_experience_thread(config, _db_dir)


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
_thread_lock = threading.Lock()


def _ensure_experience_thread(config: dict, db_dir: str):
    """确保蒸馏线程已启动"""
    global _experience_thread
    with _thread_lock:
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


def clear_all_sessions_cache():
    """清除所有会话的内存缓存（配合 clear_all_sessions 使用）"""
    global _session_stores
    _session_stores.clear()


def process_message(message: str, config: dict, session_id: str = None, on_tool_call: callable = None) -> tuple:
    """
    处理消息，返回 (response_content, session_id, files)。
    files 为该轮生成的下载文件列表。
    支持多会话：每请求使用独立的噪声/滑块实例，无全局锁。
    on_tool_call: 可选回调，在每次工具调用后触发，参数为 (name, args, result)。
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

    try:
        return _process_message_inner(message, config, store, actual_session_id, saved_soul, saved_name, on_tool_call, noise, slider, _pending_files)
    finally:
        if saved_soul is not None:
            config["identity"]["soul"] = saved_soul
        if saved_name is not None:
            config["identity"]["name"] = saved_name


def _process_message_inner(message, config, store, actual_session_id, saved_soul, saved_name, on_tool_call, noise, slider, _pending_files):
    """process_message 的内部实现，由 process_message 通过 try/finally 调用以保证 config 恢复。"""
    global _last_system_prompt, _reflection_thread, _plugin_manager

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
    with _thread_lock:
        if _reflection_thread is None:
            _reflection_thread = threading.Thread(
                target=_reflect_loop, args=(config, db_dir), daemon=True
            )
            _reflection_thread.start()

    task_type = _classify_task(message)
    strength = _get_strength(task_type, config)

    # ── 立即保存用户消息（防止后台处理期间页面刷新丢失） ──
    store.save_message("user", message, task_type)

    # 加载历史（足够多，由 context_manager 按 token 智能截断）
    hist_limit = 50 if task_type == "simple" else 500
    history = store.get_recent_history(limit=hist_limit)

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
    # 只在需要工具时才注入工具提示（减少简单对话的上下文开销）
    needs_tool = any(kw in message for kw in _ACTION_KEYWORDS)
    if needs_tool:
        system_text += _build_tool_prompt()

    # 编码任务自动注入项目上下文（带 30 秒缓存，只匹配明确的编码关键词）
    _CODE_KEYWORDS = {"写代码", "改代码", "看代码", "读代码", "写程序", "调试代码",
                      "code review", "代码审查", "代码重构",
                      "git status", "git commit", "git push", "git diff", "git log",
                      "pip install", "npm install", "yarn add",
                      "grep_files", "find_definition", "edit_file",
                      "run_python", "exec_shell",
                      "bugfix", "hotfix", "refactor", "debug"}
    if any(kw in message for kw in _CODE_KEYWORDS):
        try:
            now_ts = time.time()
            # 30 秒缓存
            if not hasattr(_build_tool_prompt, '_git_ctx_cache') or \
               now_ts - getattr(_build_tool_prompt, '_git_ctx_ts', 0) > 30:
                from hedera.core.tools import call_tool as _ct
                ctx = _ct("git_status", {"path": "."})
                _build_tool_prompt._git_ctx_cache = ctx
                _build_tool_prompt._git_ctx_ts = now_ts
            else:
                ctx = _build_tool_prompt._git_ctx_cache
            if ctx.get("success"):
                ctx_parts = []
                if ctx.get("branch"):
                    ctx_parts.append(f"分支: {ctx['branch']}")
                if ctx.get("status"):
                    ctx_parts.append(f"变更:\n{ctx['status'][:500]}")
                if ctx.get("recent_commits"):
                    ctx_parts.append(f"最近提交:\n{ctx['recent_commits'][:500]}")
                if ctx.get("file_tree"):
                    ctx_parts.append(f"项目结构:\n{ctx['file_tree'][:1500]}")
                if ctx_parts:
                    system_text += f"\n\n【当前项目上下文 - 自动注入】\n" + "\n".join(ctx_parts)
        except Exception:
            pass  # 静默失败，不影响正常流程

    user_message = message

    # 噪声处理（需要工具时跳过，否则会导致回复错乱）
    extra_messages = []
    if not needs_tool and task_type != "simple" and config.get("noise", {}).get("enabled", True):
        if strength < 0.1:
            noise_type = "gaussian"
        elif strength < 0.2:
            noise_type = "poisson"
        else:
            noise_type = "impulse"
        noised_msg, jumps = noise.inject(user_message, strength, noise_type=noise_type)
        if noised_msg != user_message:
            extra_messages.append({"role": "user", "content": noised_msg})
        if jumps:
            store.save_noise_jumps(jumps)
            for j in jumps:
                if j["type"] == "poisson":
                    slider.adjust("drive", -0.08)
                elif j["type"] == "impulse":
                    slider.adjust("thinking", 0.1)
                    slider.adjust("drive", -0.15)
            store.save_slider_state(slider.state.to_dict())

    if needs_tool:
        extra_messages.append({
            "role": "user",
            "content": "（先调合适的工具获取信息，再回答。工具出错就换方式。）"
        })

    # 防止 LLM 回显工具原始输出
    extra_messages.append({
        "role": "system",
        "content": "重要规则：工具返回的内容是参考资料，不是你的回答。严禁原样输出工具返回的文件内容、代码全文、命令输出。用自己的话总结，只引用关键片段（每段不超过10行）。需要展示代码时只写用户需要修改的部分。"
    })

    # 使用 context_manager 智能截断上下文
    model_name = config.get("model", {}).get("name", "")
    max_ctx = config.get("model", {}).get("context_window", 0) or estimate_max_context(model_name)
    tools_text = _build_tool_prompt() if needs_tool else ""

    msgs, _ctx_stats = build_context_messages(
        system_text=system_text,
        history=history,
        user_message=user_message,
        extra_messages=extra_messages,
        max_context_tokens=max_ctx,
        reserve_for_response=config.get("model", {}).get("max_tokens", 4096),
        tools_text=tools_text,
    )

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

            # 特殊工具：report_progress — 中间汇报给用户，不中断流程
            if func_name == "report_progress":
                progress_text = func_args.get("text", "")
                if progress_text and on_tool_call:
                    try:
                        on_tool_call("report_progress", func_args, {"success": True, "reported": True})
                    except Exception:
                        pass
                # 存入消息历史，让 LLM 知道已汇报
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{tool_loop_count}"),
                    "content": json.dumps({"success": True, "message": f"已汇报给用户: {progress_text[:100]}"}, ensure_ascii=False),
                })
                continue

            # 检查用户是否插嘴（有新消息则中断当前任务）
            if _check_user_interrupt(store, message):
                final_content = "（任务被用户中断）"
                break

            # 先查核心工具，再查插件工具
            tool_result = call_tool(func_name, func_args)

            # 记录 generate_image 的 markdown 结果，用于注入回复
            if func_name == "generate_image" and tool_result.get("success") and tool_result.get("markdown"):
                try:
                    _call_api._last_img_markdown = tool_result["markdown"]
                except Exception:
                    pass

            # 实时回调 + 进度存储：通知前端工具调用进度
            if on_tool_call:
                try:
                    on_tool_call(func_name, func_args, tool_result)
                except Exception:
                    pass

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
            # 编码相关工具保留更多输出（1M 上下文下可以给更多空间）
            _code_tools = {"exec_shell", "run_python", "read_file", "grep_files"}
            _max_resp = 15000 if func_name in _code_tools else 8000
            if len(tool_response) > _max_resp:
                tool_response = tool_response[:_max_resp - 500] + "\n...（结果过长已截断）"

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

    # 如果本轮有工具调用且生成了文件，检查回复是否混入代码
    if _pending_files and tool_loop_count > 0 and final_content:
        has_code = (len(final_content) > 200 and
                    any(k in final_content for k in ["def ", "import ", "class ", "function ",
                                                     "powershell", "cmd /c", "<invoke", "#!/bin/"]))
        if has_code:
            try:
                clean_msgs = msgs[:1] + [
                    {"role": "user", "content": f"你刚才调用工具完成了任务。请用一句简洁的话告诉用户任务已完成，附上文件名。不要输出任何代码或命令。"}
                ]
                clean_result = _call_api(clean_msgs, config, tools=[], temperature_override=0.3)
                clean_text = clean_result.get("content", "")
                if clean_text and len(clean_text) < 500:
                    final_content = clean_text
            except Exception:
                pass

    # 后处理自检（如果已经做过代码清理，跳过自检，避免重复）
    if not _pending_files and task_type in ("complex", "creative") and strength > 0.1:
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

    # 如果本轮调用了 generate_image 并成功了，把 markdown 图片注入回复开头
    if hasattr(_call_api, '_last_img_markdown') and _call_api._last_img_markdown:
        md = _call_api._last_img_markdown
        if md not in final_content:
            final_content = md + "\n\n" + final_content
        _call_api._last_img_markdown = None
    if hasattr(_call_api, '_last_img_markdown'):
        _call_api._last_img_markdown = None

    # 用户发了消息 → 重置自提问无回答计数
    global _proactive_unanswered
    _proactive_unanswered = 0

    # 防重复：检测回复中是否有重复段落，有则截断
    if final_content and len(final_content) > 100:
        lines = [l.strip() for l in final_content.split('\n') if l.strip()]
        if len(lines) > 3:
            seen = set()
            deduped = []
            for line in lines:
                # 短行（<30字）不参与去重，避免误伤格式行
                if len(line) < 30:
                    deduped.append(line)
                    continue
                if line in seen:
                    break  # 发现重复，截断后续内容
                seen.add(line)
                deduped.append(line)
            if len(deduped) < len(lines):
                final_content = '\n'.join(deduped)

    # 用户消息已在请求开头保存，此处只保存助手回复
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


def get_last_api_usage():
    """返回最近一次 API 调用的 token 用量"""
    with _usage_lock:
        return dict(_last_api_usage)


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
