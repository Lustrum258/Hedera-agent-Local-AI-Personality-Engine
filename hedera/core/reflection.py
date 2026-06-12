"""
Hedera reflection and experience distillation system
"""

import os
import re
import threading
import time
import datetime as dt

from hedera.core.memory import build_system_prompt
from hedera.core.memory_store import MemoryStore
from hedera.core.experience import distill_experience_once
from hedera.core.api import _call_api

# --- State ---
_shutdown_event = threading.Event()
_reflection_log = []
_reflection_details = []
_experience_log = []
_last_distill_time = 0

_proactive_unanswered = 0
_PROACTIVE_MAX_UNANSWERED = 3

_reflection_thread = None
_experience_thread = None
_thread_lock = threading.Lock()


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


def _ensure_reflection_thread(config: dict, db_dir: str):
    global _reflection_thread
    with _thread_lock:
        if _reflection_thread is None:
            _reflection_thread = threading.Thread(
                target=_reflect_loop, args=(config, db_dir), daemon=True
            )
            _reflection_thread.start()


def get_reflection_log():
    """暴露自省日志（供 HTTP API 调用）"""
    return _reflection_log


def get_reflection_details():
    """暴露自省完整维度（供 HTTP API 调用）"""
    return _reflection_details


def get_experience_log():
    """暴露蒸馏日志（供 HTTP API 调用）"""
    return _experience_log
