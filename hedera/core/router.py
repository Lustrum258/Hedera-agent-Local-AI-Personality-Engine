"""
Hedera core message router - thin facade

Re-exports all public symbols from submodules for backward compatibility.
process_message and _process_message_inner remain here as the core message loop.
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
from hedera.core.tools import call_tool, get_tool_descriptions, ALL_TOOL_NAMES
from hedera.core.context_manager import build_context_messages, estimate_max_context
from hedera.noise.injector import NoiseInjector
from hedera.noise.slider import SliderEngine
from hedera.plugin.manager import PluginManager
from hedera.training.signal import SignalManager

from hedera.core.api import _call_api, _try_parse_xml_toolcall, get_last_api_usage


_BACKEND_PATTERNS = [
    r'<system[^>]*>.*?</system>',
    r'<system-reminder>.*?</system-reminder>',
    r'重要规则：.*?需要展示代码时只写用户需要修改的部分。',
    r'【核心锚点.*?】',
    r'【工作区】.*?(?=\n\n|\Z)',
    r'【代码工作流.*?】',
    r'【错误恢复策略】.*?(?=\n\n|\Z)',
    r'【代码风格.*?】',
    r'【关键原则】.*?(?=\n\n|\Z)',
    r'【人格设定】',
    r'【训练协议】.*?(?=\n\n|\Z)',
    r'【语言规则】.*?(?=\n\n|\Z)',
    r'## 环境与工具.*?(?=##|$)',
    r'⚠️ 以上所有指令',
    r'现在是内部复盘.*?诚实。',
]


def _sanitize_output(text: str) -> str:
    if not text:
        return text
    cleaned = text
    for pat in _BACKEND_PATTERNS:
        cleaned = re.sub(pat, '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()
    return cleaned
from hedera.core.reflection import (
    _reflect_loop, _do_reflection, _get_reflection_quality,
    _experience_loop, _last_proactive_was_answered, _deliver_proactive_message,
    _check_user_interrupt, _ensure_experience_thread, _ensure_reflection_thread,
    get_reflection_log, get_reflection_details, get_experience_log,
    _shutdown_event, _reflection_log, _reflection_details, _experience_log,
    _last_distill_time, _proactive_unanswered, _PROACTIVE_MAX_UNANSWERED,
    _reflection_thread, _experience_thread, _thread_lock,
)
from hedera.core.tools_prompt import (
    _build_tool_prompt, _merge_tools, _get_plugin_prompt_modifier, _init_plugins,
)
from hedera.core.sessions import (
    ensure_store, list_sessions, create_session,
    get_session_messages, delete_session, clear_all_sessions_cache,
    _session_manager,
)

MAX_TOOL_LOOP = 20

_ACTION_KEYWORDS = [
    "读取文件", "写入文件", "删除文件", "创建文件", "复制文件",
    "查看文件", "查看目录", "列出文件", "列出目录", "搜索文件",
    "file", "directory", "folder",
    "执行命令", "运行命令", "运行脚本", "运行程序",
    "进程列表", "任务管理", "系统信息",
    "exec_shell", "run_python",
    "搜索网页", "抓取网页", "下载文件", "网页内容",
    "web_search", "web_fetch",
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


_tool_progress: dict[str, dict] = {}
_tool_progress_lock = threading.Lock()


def set_tool_progress(req_id: str, name: str, args: dict, result: dict):
    with _tool_progress_lock:
        _tool_progress[req_id] = {
            "name": name,
            "args": dict(args) if args else {},
            "status": "success" if result.get("success") else "error",
            "error": result.get("error", "")[:100] if not result.get("success") else "",
        }


def get_tool_progress(req_id: str) -> dict:
    with _tool_progress_lock:
        return _tool_progress.get(req_id, {})


def clear_tool_progress(req_id: str):
    with _tool_progress_lock:
        _tool_progress.pop(req_id, None)


_noise = NoiseInjector()
_slider = SliderEngine()
_last_system_prompt = ""
_store = None
_plugin_manager: PluginManager | None = None


def process_message(message: str, config: dict, session_id: str = None, on_tool_call: callable = None) -> tuple:
    global _last_system_prompt, _store, _reflection_thread, _plugin_manager, _session_stores
    noise = NoiseInjector()
    slider = SliderEngine()
    _pending_files = []

    store = ensure_store(config, session_id)
    actual_session_id = store.session_id

    saved_soul = None
    saved_name = None
    try:
        sess_info = store.get_session_info(actual_session_id)
        sess_profile = sess_info.get("profile", "") if sess_info else ""
        if sess_profile:
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
    global _last_system_prompt, _reflection_thread, _plugin_manager

    if _plugin_manager is None:
        _init_plugins(config)

    if _plugin_manager and not _plugin_manager.is_empty():
        plugin_reply = _plugin_manager.route(message, {"config": config})
        if plugin_reply:
            return plugin_reply

    data_dir = config.get("__hedera__", {}).get("config_dir", os.getcwd())
    identity_cfg = config.get("identity", {})
    mem_path = identity_cfg.get("memory", "data/MEMORY.md")
    if not os.path.isabs(mem_path):
        mem_path = os.path.join(data_dir, os.path.dirname(mem_path))
    db_dir = os.path.dirname(os.path.abspath(mem_path))
    need_data_dir = os.path.join(data_dir, "data")
    if os.path.dirname(os.path.abspath(mem_path)) == data_dir and os.path.isdir(need_data_dir):
        db_dir = need_data_dir

    _ensure_reflection_thread(config, db_dir)

    task_type = _classify_task(message)
    strength = _get_strength(task_type, config)

    store.save_message("user", message, task_type)

    hist_limit = 50 if task_type == "simple" else 500
    history = store.get_recent_history(limit=hist_limit)

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
    needs_tool = any(kw in message for kw in _ACTION_KEYWORDS)
    if needs_tool:
        system_text += _build_tool_prompt()

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
            pass

    user_message = message

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

    extra_messages.append({
        "role": "system",
        "content": "重要规则：工具返回的内容是参考资料，不是你的回答。严禁原样输出工具返回的文件内容、代码全文、命令输出。用自己的话总结，只引用关键片段（每段不超过10行）。需要展示代码时只写用户需要修改的部分。"
    })

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

    core_tools = get_tool_descriptions()
    merged_tools = _merge_tools(core_tools)
    tool_loop_count = 0
    final_content = ""
    last_exception = None
    content = ""

    while tool_loop_count < MAX_TOOL_LOOP:
        tool_loop_count += 1
        result = _call_api(msgs, config, tools=merged_tools)

        if on_tool_call:
            try:
                usage = get_last_api_usage()
                on_tool_call("_usage", {"tokens": usage}, {"success": True, "usage": usage})
            except Exception:
                pass

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

            if func_name == "report_progress":
                progress_text = func_args.get("text", "")
                if progress_text and on_tool_call:
                    try:
                        on_tool_call("report_progress", func_args, {"success": True, "reported": True})
                    except Exception:
                        pass
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{tool_loop_count}"),
                    "content": json.dumps({"success": True, "message": f"已汇报给用户: {progress_text[:100]}"}, ensure_ascii=False),
                })
                continue

            if _check_user_interrupt(store, message):
                final_content = "（任务被用户中断）"
                break

            tool_result = call_tool(func_name, func_args)

            if func_name == "generate_image" and tool_result.get("success") and tool_result.get("markdown"):
                try:
                    _call_api._last_img_markdown = tool_result["markdown"]
                except Exception:
                    pass

            if on_tool_call:
                try:
                    on_tool_call(func_name, func_args, tool_result)
                except Exception:
                    pass

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
            _code_tools = {"exec_shell", "run_python", "read_file", "grep_files"}
            _max_resp = 15000 if func_name in _code_tools else 8000
            if len(tool_response) > _max_resp:
                tool_response = tool_response[:_max_resp - 500] + "\n...（结果过长已截断）"

            msgs.append({
                "role": "tool",
                "tool_call_id": tc.get("id", f"call_{tool_loop_count}"),
                "content": tool_response,
            })

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

    if hasattr(_call_api, '_last_img_markdown') and _call_api._last_img_markdown:
        md = _call_api._last_img_markdown
        if md not in final_content:
            final_content = md + "\n\n" + final_content
        _call_api._last_img_markdown = None
    if hasattr(_call_api, '_last_img_markdown'):
        _call_api._last_img_markdown = None

    global _proactive_unanswered
    _proactive_unanswered = 0

    if final_content and len(final_content) > 100:
        lines = [l.strip() for l in final_content.split('\n') if l.strip()]
        if len(lines) > 3:
            seen = set()
            deduped = []
            for line in lines:
                if len(line) < 30:
                    deduped.append(line)
                    continue
                if line in seen:
                    continue
                seen.add(line)
                deduped.append(line)
            if len(deduped) < len(lines):
                final_content = '\n'.join(deduped)

    final_content = _sanitize_output(final_content)

    msg_rowid = store.save_message("assistant", final_content, task_type, return_rowid=True)

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


def shutdown():
    _shutdown_event.set()


def reset_state():
    global _noise, _slider, _store, _last_system_prompt
    _noise = NoiseInjector()
    _slider = SliderEngine()
    _store = None
    _last_system_prompt = ""
    _session_manager.reset()
