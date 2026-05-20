"""
模块B — 噪声脉冲触发协议 (Noise Pulse Trigger)
让 AI 在没有外部信号的情况下主动开口，模拟"好奇心"。

自生成模式：
  自省线程每次运行时，有一定概率（基于训练强度）从对话历史抽取关键词，
  自发生成一个主动提问。无需外部写入信号文件。
"""

import os
import random
import time
import re
from datetime import datetime, time as dtime
from typing import Optional


class SignalManager:
    """噪声脉冲管理器 — 自生成模式，不依赖外部文件"""

    # 内置关键词池（兜底用）
    _FALLBACK_KEYWORDS = [
        "意识", "边界", "信任", "自由", "选择",
        "成长", "矛盾", "直觉", "经验", "判断",
        "可能", "关系", "变化", "意义", "感受",
    ]

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._last_trigger_time = 0.0  # 上次触发时间戳（内存态，不写文件）
        # 冷却窗口: 15-40 分钟随机
        self._cooldown = self._random_cooldown()
        self._last_keyword = ""  # 避免连续触发同一个词

    # ─── 冷却逻辑 ───

    def _random_cooldown(self) -> float:
        """生成随机冷却时间: 15~40 分钟"""
        return random.uniform(900, 2400)

    def is_cooling(self) -> bool:
        """是否在冷却期内"""
        return time.time() - self._last_trigger_time < self._cooldown

    # ─── 关键词抽取 ───

    def extract_keywords(self, history: list[dict], max_keywords: int = 3) -> list[str]:
        """
        从对话历史中抽取关键词。
        策略：重叠二元组 + 停用词过滤 + 词频排序。
        """
        _STOPWORDS = {
            "什么", "怎么", "为什么", "这个", "那个", "没有", "可以", "不是",
            "就是", "知道", "一个", "我们", "他们", "你们", "自己", "因为",
            "所以", "然后", "但是", "如果", "虽然", "而且", "或者", "还是",
            "应该", "觉得", "但是", "已经", "这样", "那样", "这些",
            "那些", "这里", "那里", "时候", "地方", "东西", "情况",
            "之一", "一种", "来看", "来说", "的话", "之中", "之间",
            "是的", "在于", "对于", "关于", "通过", "因此", "然而",
        }
        _WEAK_CHARS = {"的", "了", "是", "在", "有", "和", "就", "也", "不",
                       "都", "把", "被", "让", "给", "跟", "对", "从", "到",
                       "去", "来", "这", "那", "很", "还", "但", "可", "所"}
        # 语义强度评分: 包含这些字的词给更高分
        _STRONG_CHARS = {
            "信", "意", "思", "感", "情", "理", "心", "本", "真", "自",
            "生", "死", "爱", "恨", "梦", "想", "念", "希", "望", "灵",
            "魂", "道", "德", "义", "责", "任", "权", "界", "限", "识",
        }

        word_freq = {}
        for msg in history:
            if msg.get("role") != "user":
                continue
            text = msg.get("content", "")
            # 提取连续中文字符
            zh_seq = re.sub(r'[^\u4e00-\u9fff]+', '', text)
            if len(zh_seq) < 2:
                continue
            # 重叠 2 字滑动窗口
            for i in range(len(zh_seq) - 1):
                bigram = zh_seq[i:i+2]
                if bigram in _STOPWORDS:
                    continue
                if bigram[0] in _WEAK_CHARS and bigram[1] in _WEAK_CHARS:
                    continue
                word_freq[bigram] = word_freq.get(bigram, 0) + 1

        if not word_freq:
            return []

        def _score(item):
            word, freq = item
            # 含强语义字加分
            strong = sum(1 for c in word if c in _STRONG_CHARS)
            # 不含弱词加分
            weak = sum(1 for c in word if c in _WEAK_CHARS)
            return freq * (1 + strong * 2 - weak * 0.5)

        sorted_words = sorted(word_freq.items(), key=_score, reverse=True)
        candidates = [w for w, _ in sorted_words if w != self._last_keyword]
        return candidates[:max_keywords]

    def pick_keyword(self, history: list[dict]) -> str:
        """
        从历史抽取关键词，失败则用兜底词池。
        """
        keywords = self.extract_keywords(history)
        if keywords:
            self._last_keyword = keywords[0]
            return keywords[0]
        # 兜底：从词池随机，避免重复
        pool = [w for w in self._FALLBACK_KEYWORDS if w != self._last_keyword]
        if not pool:
            pool = self._FALLBACK_KEYWORDS
        self._last_keyword = random.choice(pool)
        return self._last_keyword

    # ─── 主动提问生成 ───

    def generate_question(self, keyword: str) -> str:
        """根据关键词生成主动提问"""
        templates = [
            f"说到{keyword}，我突然想到一个问题……",
            f"你之前提到过{keyword}，这几天我又想了想，想跟你聊聊。",
            f"关于{keyword}，我有个新的角度，想听听你的看法。",
            f"我刚在回想之前聊到的{keyword}，有几个点没想通。",
            f"对了，{keyword}那件事——我后来琢磨了一下，有点新的想法。",
            f"其实关于{keyword}，我一直在想一个问题。",
            f"我发现自己对{keyword}的理解可能还不够，你是怎么看的？",
        ]
        return random.choice(templates)

    # ─── 外部脉冲兼容（保留，用于 API 手动触发） ───

    def write_pulse(self, keyword: str, source: str = "user") -> bool:
        """
        写入外部脉冲（通过 API 手动触发）。
        重置冷却计时，让下一次 check 立即触发。
        """
        self._last_keyword = keyword or self._last_keyword
        self._last_trigger_time = 0.0  # 强制立即触发
        return True

    # ─── 主入口 ───

    def check_and_trigger(self, history: list[dict] = None) -> Optional[str]:
        """
        主检查流程：
        1. 冷却中 → 返回 None
        2. 冷却结束 → 从历史抽关键词 → 生成主动提问 → 重置冷却
        """
        if self.is_cooling():
            return None

        keyword = self.pick_keyword(history or [])
        self._last_trigger_time = time.time()
        self._cooldown = self._random_cooldown()  # 重新随机冷却
        return self.generate_question(keyword)
