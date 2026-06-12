"""
上下文管理器
解决两个问题：
1. 上下文拼接时智能截断，不超出模型窗口
2. 实时统计已使用的 token 数量
"""

import json
from typing import Optional

try:
    import tiktoken
    # cl100k_base 近似（DeepSeek/GPT-4 同编码）
    _ENCODER = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _ENCODER = None


class ContextStats:
    """上下文统计信息，可序列化返回给前端"""
    def __init__(self):
        self.system_tokens = 0
        self.history_tokens = 0
        self.user_tokens = 0
        self.tool_tokens = 0      # 工具定义占的 token
        self.total_tokens = 0
        self.max_context = 0      # 模型上限
        self.utilization = 0.0    # 使用率 0~1
        self.messages_included = 0  # 实际纳入的历史消息数
        self.messages_dropped = 0   # 被截断丢弃的消息数

    def to_dict(self) -> dict:
        return {
            "system_tokens": self.system_tokens,
            "history_tokens": self.history_tokens,
            "user_tokens": self.user_tokens,
            "tool_tokens": self.tool_tokens,
            "total_tokens": self.total_tokens,
            "max_context": self.max_context,
            "utilization": round(self.utilization, 3),
            "messages_included": self.messages_included,
            "messages_dropped": self.messages_dropped,
        }

    def __repr__(self):
        pct = f"{self.utilization * 100:.1f}%"
        return (
            f"ContextStats(total={self.total_tokens}/{self.max_context} ({pct}), "
            f"system={self.system_tokens}, history={self.history_tokens}, "
            f"user={self.user_tokens}, included={self.messages_included}, "
            f"dropped={self.messages_dropped})"
        )


def count_tokens(text: str) -> int:
    """计算文本的 token 数"""
    if not text:
        return 0
    if _ENCODER:
        return len(_ENCODER.encode(text))
    # fallback: 粗略估算（中文约 1.5 字/token，英文约 4 字符/token）
    cn_chars = sum(1 for c in text if ord(c) > 0x4E00)
    en_chars = len(text) - cn_chars
    return int(cn_chars / 1.5 + en_chars / 4)


def count_message_tokens(message: dict) -> int:
    """计算单条消息的 token 数（含 role 开销）"""
    # 每条消息有固定开销：role + 分隔符 ≈ 4 tokens
    overhead = 4
    content = message.get("content", "")
    # 工具调用也要算
    tool_calls = message.get("tool_calls")
    if tool_calls:
        content += json.dumps(tool_calls, ensure_ascii=False)
    return count_tokens(content) + overhead


def build_context_messages(
    system_text: str,
    history: list[dict],
    user_message: str,
    extra_messages: list[dict] = None,
    max_context_tokens: int = 128000,
    reserve_for_response: int = 8192,
    tools_text: str = "",
) -> tuple[list[dict], ContextStats]:
    """
    智能构建上下文消息列表。

    策略：
    1. system prompt 始终保留
    2. 从最新的历史消息往前加，直到接近上限
    3. 如果历史消息太多，丢弃最旧的
    4. 用户消息始终保留

    返回: (messages_list, stats)
    """
    stats = ContextStats()
    stats.max_context = max_context_tokens

    # 可用 token 预算 = 总上限 - 预留给回复的空间
    available_budget = max_context_tokens - reserve_for_response

    # 计算 system prompt 的 token
    system_tokens = count_tokens(system_text)
    stats.system_tokens = system_tokens

    # 计算工具定义的 token
    tools_tokens = count_tokens(tools_text) if tools_text else 0
    stats.tool_tokens = tools_tokens

    # 计算用户消息的 token
    user_tokens = count_message_tokens({"role": "user", "content": user_message})
    stats.user_tokens = user_tokens

    # 计算额外消息（如噪声注入、工具提示）的 token
    extra_tokens = 0
    if extra_messages:
        for em in extra_messages:
            extra_tokens += count_message_tokens(em)

    # 固定开销
    fixed_tokens = system_tokens + tools_tokens + user_tokens + extra_tokens

    # 历史消息可用的预算
    history_budget = available_budget - fixed_tokens

    if history_budget <= 0:
        # system prompt 太长，历史全部丢弃
        stats.messages_dropped = len(history)
        msgs = [{"role": "system", "content": system_text}]
        msgs.append({"role": "user", "content": user_message})
        if extra_messages:
            # 把额外消息插在用户消息之前
            for em in extra_messages:
                msgs.insert(-1, em)
        stats.total_tokens = fixed_tokens
        stats.utilization = fixed_tokens / max_context_tokens
        return msgs, stats

    # 从最新消息往前取
    selected_history = []
    current_tokens = 0
    dropped = 0

    for msg in reversed(history):
        msg_tokens = count_message_tokens(msg)
        if current_tokens + msg_tokens > history_budget:
            dropped += 1
            continue
        selected_history.insert(0, msg)
        current_tokens += msg_tokens

    stats.history_tokens = current_tokens
    stats.messages_included = len(selected_history)
    stats.messages_dropped = dropped
    stats.total_tokens = fixed_tokens + current_tokens
    stats.utilization = stats.total_tokens / max_context_tokens

    # 组装最终消息列表
    msgs = [{"role": "system", "content": system_text}]

    # 插入历史消息
    for h in selected_history:
        msgs.append({"role": h["role"], "content": h["content"]})

    # 插入额外消息
    if extra_messages:
        msgs.extend(extra_messages)

    # 最后是用户消息
    msgs.append({"role": "user", "content": user_message})

    return msgs, stats


def estimate_max_context(model_name: str) -> int:
    """根据模型名估算上下文窗口大小"""
    model_lower = model_name.lower()

    # 常见模型的上下文窗口
    known_windows = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "deepseek-v4": 1048576,
        "deepseek-reasoner": 1048576,
        "deepseek-coder": 1048576,
        "deepseek-chat": 1048576,
        "deepseek": 1048576,
        "gemini": 1048576,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "claude": 200000,
        "qwen": 128000,
        "yi": 200000,
        "mimo": 1048576,
    }

    for key, window in known_windows.items():
        if key in model_lower:
            return window

    # 默认保守估计
    return 32000


# ─── 全局统计（供 API 查询） ───

_last_stats: Optional[ContextStats] = None


def set_last_stats(stats: ContextStats):
    global _last_stats
    _last_stats = stats


def get_last_stats() -> Optional[ContextStats]:
    return _last_stats
