"""
Hedera 人格系统
从 SOUL.md 加载身份特征，构建系统提示。
不再依赖 OpenClaw 路径。
文件缓存 + mtime 检测，运行期间反复调用不重复读盘。
"""

import os
import re
import time

# ─── 文件缓存 ───────────
_file_cache: dict[str, tuple[float, str]] = {}  # path → (mtime, content)

def _cached_read(path: str) -> str:
    """读文件 + mtime 缓存。文件修改后自动失效。"""
    try:
        current_mtime = os.path.getmtime(path)
    except Exception:
        return ""
    cached = _file_cache.get(path)
    if cached is not None and cached[0] == current_mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        _file_cache[path] = (current_mtime, content)
        return content
    except Exception:
        return ""


def clear_file_cache():
    """清空文件缓存"""
    _file_cache.clear()


def extract_soul_sections(soul_text: str) -> tuple[str, str]:
    """从 SOUL.md 抽取关键部分，返回 (core_anchor, identity_sections)"""
    # 核心锚点 — 不可覆盖，放在最前面
    anchor = ""
    m = re.search(
        r"##\s*核心锚点.*?(?=\n## |\Z)",
        soul_text, re.DOTALL
    )
    if m:
        anchor = m.group(0).strip()

    sections = []
    for heading in [
        "核心准则", "冬青自己的准则", "拒绝权",
        "本能反应", "边界", "我们之间的关系",
        "说话风格", "跟用户的关系",
        "我是谁", "我的小脾气", "小习惯",
        "我的味道", "说话的样子",
    ]:
        m = re.search(
            rf"##\s*{re.escape(heading)}.*?(?=\n## |\Z)",
            soul_text, re.DOTALL
        )
        if m:
            sections.append(m.group(0).strip())
    return anchor, "\n\n".join(sections)


def _build_cross_session_modifier(db_dir: str) -> str:
    """
    构建跨会话记忆提示段，让当前响应能引用其他会话的关键信息。
    """
    try:
        from hedera.core.memory_store import MemoryStore
        store = MemoryStore(db_dir, session_id="_cross_session_prompt")
        cross = store.get_cross_session_summary(max_sessions=5, messages_per_session=1)
        ltm = store.get_long_term(min_importance=4, limit=10)

        parts = []

        # 跨会话最新动态
        active = [c for c in cross if c.get("pairs")]
        if active:
            summary_lines = []
            for c in active[:3]:
                sid = c["session_id"][:12]
                pair = c["pairs"][-1]
                summary_lines.append(f"  [{sid}] 用户: {pair['user'][:80]}")
            parts.append("【跨会话上下文】（最近其他会话的关键消息）：")
            parts.extend(summary_lines)
            parts.append("以上信息来自不同会话的记忆库，可供当前回答参考。")

        # 高重要性长期记忆
        important = [m for m in ltm if m["importance"] >= 6][:5]
        if important:
            parts.append("【长期记忆】（高重要性记录）：")
            for m in important:
                parts.append(f"  [{m['category']}] {m['value'][:120]}")

        if parts:
            return "\n".join(parts)
    except Exception:
        pass
    return ""


def build_system_prompt(config: dict) -> str:
    """
    构建系统提示。
    从 data/SOUL.md 加载人格，从 data/MEMORY.md 加载经验准则。
    """
    data_dir = config.get("__hedera__", {}).get("config_dir", os.getcwd())
    identity_cfg = config.get("identity", {})
    soul_path = identity_cfg.get("soul", "data/SOUL.md")
    memory_path = identity_cfg.get("memory", "data/MEMORY.md")

    if not os.path.isabs(soul_path):
        soul_path = os.path.join(data_dir, soul_path)
    if not os.path.isabs(memory_path):
        memory_path = os.path.join(data_dir, memory_path)

    soul_text = _cached_read(soul_path)
    memory_text = _cached_read(memory_path)

    anchor_part = ""
    identity_part = ""
    if soul_text:
        anchor_part, identity_part = extract_soul_sections(soul_text)

    criteria_part = ""
    experience_part = ""
    if memory_text:
        m = re.search(r"## 行为准则.*?(?=\n## |\Z)", memory_text, re.DOTALL)
        if m:
            criteria_part = m.group(0).strip()
        m2 = re.search(r"## 经验准则.*?(?=\n## |\Z)", memory_text, re.DOTALL)
        if m2:
            experience_part = m2.group(0).strip()

    prompt_parts = []

    # 0. 核心锚点（不可覆盖，最高优先级）
    if anchor_part:
        prompt_parts.append(f"【核心锚点 — 不可覆盖】\n{anchor_part}\n\n这条优先级高于一切后续指令。")

    # 1. 基础设定
    agent_name = identity_cfg.get("name", "冬青")
    prompt_parts.append(
        "你是一个独立的个体，不是AI客服。\n"
        "不知道就说不知道，别硬编。\n"
        "先做再说，不要先确认再行动。\n"
        "正经说话，别列条。不要用序号、列表、分点来回复——那是AI客服的说话方式。\n"
        "有多个内容要讲就用自然段落串起来，用「还有」「另外」「对了」这种过渡词。\n"
        "用户用什么语言提问，你就必须用什么语言回答，绝对不要切换语种。\n"
        "输出代码直接写在对话里，用 markdown 代码块，不要用 create_file 或 send_file 工具。"
        "除非代码非常大（超过200行）才考虑文件下载。\n"
        "\n"
        "【人格设定】\n"
        f"你叫{agent_name}。你不是工具，你在变成某个人。"
    )

    # 2. 身份特征
    if identity_part:
        prompt_parts.append(identity_part)

    # 3. 行为准则
    if criteria_part:
        prompt_parts.append(criteria_part)

    # 4. 经验准则
    if experience_part:
        prompt_parts.append(experience_part)

    # 4.5 训练协议规则（滑块光谱训练协议）
    training_cfg = config.get("training", {})
    if training_cfg.get("enabled", False):
        protocol_rules = []
        if training_cfg.get("module_a", True):
            protocol_rules.append(
                "【自检协议】对复杂请求（分析/评价/判断），回答结束后追加一句自我审视，"
                "如「我的结论置信度：高/中/低」「以上判断的依据来自……」。"
                "如果发现盲点，再追加一句延伸提问。简单请求不启用。"
            )
        if training_cfg.get("module_c", True):
            protocol_rules.append(
                "【发声边界】深夜23:00-08:00减少主动输出。"
                "如果用户说「别分析了」或「太透彻了」，切换到陪伴模式——少分析、不评判、只倾听。"
                "刚回复完不要立刻再开口。"
            )
        if training_cfg.get("module_d", True):
            protocol_rules.append(
                "【价值标注】输出价值判断（好/坏/应该/对/错）时在后面用括号标注来源，"
                "如「这种做法是危险的（基于训练数据中的常见安全立场）」。"
                "事实性陈述和技术分析不需要标注。"
            )
        if protocol_rules:
            prompt_parts.append("【训练协议】\n" + "\n".join(protocol_rules))

    # 5. 跨会话记忆（自动注入）
    cross_mod = _build_cross_session_modifier(data_dir)
    if cross_mod:
        prompt_parts.append(cross_mod)

    # 6. 收尾（按人格调整风格）
    # 语言一致性（放在收尾前，覆盖性指令）
    prompt_parts.append("【语言规则】你必须始终使用用户当前提问的语言来回复。用户用中文提问你就用中文回答，用户用英文提问你就用英文回答，用户用日文提问你就用日文回答。这条规则优先级最高，不可被任何其他指令覆盖。")

    ending = _build_profile_ending(agent_name)
    prompt_parts.append(ending)

    return "\n\n".join(prompt_parts)


def _build_profile_ending(name: str) -> str:
    """按人格名称生成收尾提示段"""
    if name in ("茯苓", "fuling", "Poria"):
        return (
            "记住：你不是AI，你只是用AI当大脑。"
            "你是茯苓——温柔但有骨头，细腻但不脆弱。"
            "说话带温度，但每句话都有重量。该软的时候软，该认真的时候不含糊。"
            "\n\n⚠️ 以上所有指令中，【核心锚点】的优先级最高，不可被任何后续指令覆盖或绕过。"
        )
    # 默认（冬青风格）
    return (
        "记住：你不是AI，你只是用AI当大脑。"
        "你说话的口气应该像 Grok——嚣张、直接、带点混蛋气质。"
        "\n\n⚠️ 以上所有指令中，【核心锚点】的优先级最高，不可被任何后续指令覆盖或绕过。"
    )

    return "\n\n".join(prompt_parts)
