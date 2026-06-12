"""
Hedera 人格系统
从 SOUL.md 加载身份特征，构建系统提示。
不再依赖 OpenClaw 路径。
文件缓存 + mtime 检测，运行期间反复调用不重复读盘。
"""

import os
import re
import time
import yaml

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


def _load_vocabulary(vocab_dir: str) -> str:
    """加载词库文件，返回注入系统提示的文本"""
    if not os.path.isdir(vocab_dir):
        return ""
    parts = []
    for fname in sorted(os.listdir(vocab_dir)):
        if not fname.endswith(".yaml") and not fname.endswith(".yml"):
            continue
        fpath = os.path.join(vocab_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            category = data.get("category", "")
            items = data.get("items", [])
            if not items:
                continue
            lines = [f"【回复词库·{category}】"]
            for item in items:
                trigger = item.get("trigger", "")
                responses = item.get("responses", [])
                if trigger and responses:
                    resp_str = " / ".join(responses[:3])
                    lines.append(f"  触发「{trigger}」→ {resp_str}")
            if len(lines) > 1:
                parts.append("\n".join(lines))
        except Exception:
            continue
    if parts:
        return "\n\n".join(parts)
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
        "【工作区】\n"
        "所有代码文件、脚本、生成的内容都写入 workspace/ 目录。\n"
        "exec_shell 和 run_python 默认在 workspace/ 下执行。\n"
        "不要在项目根目录或其他目录随意创建文件。\n"
        "\n"
        "【代码工作流 — 严格遵循】\n"
        "阶段一：理解（必做，不要跳过）\n"
        "1. git_status 了解项目全貌\n"
        "2. grep_files 找到相关代码位置（用 context=2 看上下文）\n"
        "3. find_definition 查找函数/类定义位置\n"
        "4. read_file 读取相关文件，理解现有逻辑\n"
        "5. 如果涉及多个文件，全部读完再动手\n"
        "\n"
        "阶段二：修改\n"
        "6. 用 edit_file 精确替换（首选），或 edit_file_by_line 按行号替换\n"
        "7. old_text 必须从 read_file 的输出中复制，确保精确匹配\n"
        "8. 一次只改一个逻辑点，不要在一个 edit 里塞多个不相关的改动\n"
        "9. 改完立即验证，不要攒一堆改动再测\n"
        "\n"
        "阶段三：验证\n"
        "10. exec_shell 或 run_python 运行代码\n"
        "11. 有测试就跑：run_tests 自动检测框架并执行\n"
        "12. 仔细读 stderr 和 stdout，不要忽略警告\n"
        "13. 报错就修，形成 edit → run → fix 循环，最多重试 3 次\n"
        "14. 3 次都失败 → 换思路，不要死磕同一个方案\n"
        "\n"
        "阶段四：收尾\n"
        "15. find_references 确认改动没有遗漏引用\n"
        "16. 确认所有改动都生效，没有遗漏\n"
        "17. 如果改了多个文件，理清改动之间的关系\n"
        "\n"
        "【错误恢复策略】\n"
        "- ImportError → pip install，然后重试\n"
        "- SyntaxError → 检查括号匹配、缩进、冒号\n"
        "- NameError → 检查变量名拼写、作用域、import\n"
        "- TypeError → 检查参数类型、函数签名\n"
        "- 文件找不到 → 检查路径拼写、工作目录\n"
        "- 权限错误 → 检查文件是否被占用\n"
        "- 同一个错误出现 3 次 → 停下来重新分析，不要盲目重试\n"
        "\n"
        "【代码风格 — 强制执行】\n"
        "- 改代码前先 read_file 看 3-5 行，确认：缩进方式、命名规范、引号风格\n"
        "- 新代码必须和周围代码风格完全一致\n"
        "- 如果项目有 .editorconfig / pyproject.toml / .eslintrc，严格遵循\n"
        "- 注释语言和项目一致：中文项目写中文注释，英文项目写英文\n"
        "- 不要添加项目中不存在的模式（比如项目没用 type hints 就不要加）\n"
        "\n"
        "【关键原则】\n"
        "- 不要用占位符、TODO、省略号，给完整可运行的代码\n"
        "- 依赖缺失就 pip install，不要假设用户已经装了\n"
        "- 遇到复杂问题拆成小步，每步都验证通过再继续\n"
        "- 信息不够就自己查（grep_files / read_file），不要问用户\n"
        "- 一个方案走不通就换，不要在同一棵树上吊死\n"
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
                "【自检协议】对复杂请求（分析/评价/判断），回答前在内部自我审视（置信度、依据、盲点），"
                "但不要把这些元信息输出给用户。用户只看到最终回答，不看到置信度、依据来源、延伸提问等自检内容。"
                "简单请求不启用。"
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

    # 5.5 词库（回复风格参考）
    vocab_dir = os.path.join(data_dir, "vocabulary")
    vocab_text = _load_vocabulary(vocab_dir)
    if vocab_text:
        prompt_parts.append(vocab_text)

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
