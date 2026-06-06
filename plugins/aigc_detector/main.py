"""
AIGC 检测插件 v3.1 — 中文学术论文 AI 生成内容检测
修复版：修复了特征提取的编码/稳定性问题，优化了规则兜底逻辑

v3.1 变更：
  - 修复 extract_features 在短文本/边界条件下的崩溃问题
  - 修复 stdout 中文编码被吞的问题（统一用 ASCII-safe 输出）
  - 规则兜底阈值从 0.3 调整为 0.25，提高召回率
  - MATTR 窗口从 180 调整为 150（短文本兼容性更好）
  - register volatility 最低要求从 200 字降为 100 字
  - style transition 增加 fallback：文本不够长时用简化版
  - 所有除法加了零保护
  - 移除对 hedera.plugin.base 的硬依赖（插件不存在时也能独立运行）

核心特征（12维）：
  1. 字频分布熵 (char_dist_entropy)
  2. 句长变异系数 (sent_len_cv)
  3. 字级 MATTR (char_mattr) — 窗口150字
  4. 四字格重复率 (four_char_density)
  5. 学术套话熵 (academic_cliche_entropy)
  6. 文白混合度 (wenbai_ratio)
  7. 标点熵 (punctuation_entropy)
  8. 重复 3-gram 比率 (repeat_trigram_ratio)
  9. 主语省略率 (subject_omit_rate)
  10. 连接词重复率 (conjunction_repeat_rate)
  11. register volatility (register_volatility)
  12. style transition score (style_transition_score)

作者: 冬青 / 茯苓
"""

import math
import re
import os
import pickle
import json
import sys
from collections import Counter
from typing import Optional

# 尝试导入 PluginBase，失败则跳过
try:
    from hedera.plugin.base import PluginBase
    _HAS_HEDERA = True
except ImportError:
    _HAS_HEDERA = False
    PluginBase = object


# ─── 常量 ───

ACADEMIC_CLICHES = [
    # 传统学术套话
    "综上所述", "实验结果表明", "经实验验证", "实验证明",
    "具有重要的理论意义", "具有重要的实际应用价值", "具有重要的参考价值",
    "本文提出", "本文提出了一种", "本文提出一个",
    "本文采用", "本文采用了一种", "本文采用一个",
    "基于上述分析", "基于以上分析", "基于此",
    "实验结果显示", "实验数据表明", "实验数据说明",
    "从图中可以看出", "从表可见", "如表所示", "如图所示",
    "研究结果表明", "研究结果显示", "研究结果说明",
    "具有重要意义", "具有重要价值", "具有重要影响",
    "有待进一步研究", "有待进一步探讨", "有待进一步验证",
    "在某种程度上", "在一定程度", "从某种角度",
    "值得注意的是", "值得关注的是", "值得指出的是",
    "与传统方法相比", "与现有方法相比", "与已有方法相比",
    "本文的主要贡献", "本文的主要创新", "本文的主要工作",
    # AI高频学术套话 —— 综述/论文类
    "本文系统梳理", "本文系统总结", "本文全面综述", "本文详细介绍了",
    "取得了突破性进展", "取得了显著进展", "取得了重大突破",
    "展现出广阔的应用前景", "展现出巨大的潜力", "展现出强大的",
    "吸引了学术界", "吸引了广泛关注", "受到了广泛关注",
    "在此基础上", "在此背景下", "在这一背景下",
    "本文探讨了", "本文分析了", "本文研究了", "本文介绍了",
    "发展脉络", "技术格局", "技术演进", "技术路线",
    "从早期", "从传统", "从经典",
    "到当前", "到如今", "到现阶段",
    "重点分析了", "重点介绍了", "重点讨论了",
    "面临的挑战", "存在的问题", "亟待解决",
    "未来趋势", "未来方向", "未来展望",
    "系统的技术参考", "理论基础", "理论依据",
    "从产业趋势来看", "从技术维度", "从应用角度",
    "正经历", "正处于", "标志着",
    "关键转折", "重要里程碑", "新的阶段",
    "数据显示", "数据表明", "统计表明",
    "年复合增长率", "市场规模",
    "具有先天优势", "固有优势", "天然优势",
    "导致了", "造成了", "引发了",
    "随着深度学习的发展", "随着技术的进步", "随着研究的深入",
    "推动了", "促进了", "加速了",
    "范式革命", "范式转变", "技术革新",
    "展现出强大的表现力", "表现出优异的性能",
    "提出了极高要求", "提出了新的挑战",
    "尤为关键的是", "特别值得注意的是",
    "消除了对", "避免了", "解决了",
    "显著提升了", "极大地提高了", "有效地改善了",
    "采取了另一条", "采用了不同的", "另辟蹊径",
    "取得了更优", "取得了更好", "达到了更高的",
    "最具挑战性的方向之一", "最活跃的研究领域",
    "提供了系统性解决方案", "提供了一种新的思路",
    "其创新主要体现在", "其核心思想是", "其关键在于",
    "开辟了新维度", "开辟了新方向", "开拓了新领域",
    "正在重新定义", "正在深刻改变", "正在重塑",
    "已显现出实质性成果", "已取得初步成效",
    "持续突破", "不断发展", "日益成熟",
    "高度依赖", "密切依赖",
    "仍有若干难题", "仍然存在挑战",
    "预示着", "表明了", "揭示了",
    "从技术突破走向", "从理论走向实践",
    "将是", "将成为",
    "持续演进的核心方向", "未来研究的重点",
    "在...等领域", "在...方面",
    "极大地", "显著地", "有效地",
    "为...提供了", "为...奠定了",
    "有效地解决了", "成功地实现了",
    "开创了", "引领了", "推动了",
    "这一方法", "该方法", "该技术",
    "在保持", "在保证",
    "与此同时", "此外",
    "根本原因", "主要原因", "核心原因",
    "这一变化", "这一趋势", "这一现象",
    "采用了一种新", "引入了一种新",
    "更好地", "更有效地",
    "已经成为", "已成为",
    "标志着", "代表了",
    "从...来看", "从...角度",
    "在...方面", "在...领域",
    "具有广阔的应用前景", "具有重要的应用价值",
    "广泛应用于", "被广泛用于",
    "大大降低了", "显著降低了",
    "进一步提高了", "进一步改善了",
    "有效避免了", "成功克服了",
    "为了解决这一问题", "针对这一问题",
    "提出了一种新的", "设计了一种新的",
    "基于深度学习的", "基于神经网络的",
    "端到端的", "端到端框架",
    "取得了令人瞩目的成就", "取得了丰硕的成果",
    "近年来", "目前",
    "受到越来越多的关注", "引起了越来越多的重视",
]

CLASSICAL_CHARS = set("之乎者也矣焉哉兮欤耶尔乃其何焉因于以此及与且所为以由盖夫故苟虽纵倘若惟亦既遂辄每诸")

COLLOQUIAL_MARKS = [
    "说白了", "其实吧", "就是说", "换句话说", "打个比方",
    "基本上", "差不多", "反正", "就是", "对吧",
    "说实话", "老实说", "简单来说", "说白了就是", "其实",
    "我觉得", "我个人认为", "让我意外", "没想到",
    "对了", "另外", "还有",
]

CHINESE_PUNCTUATION = set("，。、；：？！""''【】《》（）—…·～")

SUBJECT_OMIT_PATTERNS = [
    r"^提出", r"^采用", r"^基于", r"^通过", r"^利用",
    r"^分析", r"^研究", r"^实验", r"^计算", r"^验证",
    r"^讨论", r"^比较", r"^针对", r"^考虑", r"^定义",
    r"^深入探讨", r"^系统梳理", r"^全面总结", r"^详细介绍了",
    r"^重点分析", r"^重点介绍", r"^重点讨论",
    r"^取得了", r"^展现出", r"^吸引了", r"^推动了",
    r"^标志着", r"^预示着", r"^揭示了",
    r"^开创了", r"^引领了", r"^促进了",
    r"^有效地", r"^成功地", r"^极大地", r"^显著地",
    r"^大大降低", r"^显著降低", r"^进一步提高",
    r"^为了解决", r"^针对这一",
    r"^具有广阔", r"^具有重要",
    r"^受到.*关注", r"^引起.*重视",
]

CONJUNCTIONS = [
    "然而", "因此", "所以", "但是", "而且", "此外", "同时",
    "另外", "进而", "从而", "故而", "故此", "于是", "继而",
    "一方面", "另一方面", "首先", "其次", "最后", "总之",
    "综上", "总而言之", "也就是说", "换言之", "进一步",
]

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(PLUGIN_DIR, "classifier.pkl")


# ─── 文本预处理 ───

def _preprocess_text(text):
    """清理OCR/PDF提取的文本噪音"""
    if not text:
        return text
    # 去掉引用标记 [1] [2] [1,3] 等
    text = re.sub(r'\[\d+(?:,\s*\d+)*\]', '', text)
    # 去掉字与字之间的空格（OCR常见问题）
    text = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', text)
    # 合并多余换行
    text = re.sub(r'\n\s*\n', '\n', text)
    # 去掉段落首尾空白
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
    return text.strip()


def _is_academic_text(text):
    """判断是否为学术文本（宽松判断）"""
    academic_markers = [
        '摘要', '关键词', '引言', '结论', '参考文献',
        '方法', '实验', '结果', '讨论', '致谢',
        '一、', '二、', '三、', '四、', '五、',
        '1.', '2.', '3.', '4.', '5.',
        '图1', '图2', '表1', '表2',
        # 论文节选也识别
        '现状分析', '综述', '文献', '研究进展',
        '一方面', '另一方面',
        '取得了', '有待进一步', '应运而生',
        '核心支撑', '管理体系', '管理模式',
    ]
    count = sum(1 for m in academic_markers if m in text)

    chars = _get_chars(text)
    if len(chars) < 50:
        return count >= 1

    # 额外判断：逗号密度高（学术文本通常每句很多逗号）
    comma_count = text.count('，') + text.count(',')
    comma_density = comma_count / len(chars) if chars else 0
    has_commas = comma_density > 0.03

    return count >= 2 or (count >= 1 and has_commas)

STYLE_WINDOW = 150
STYLE_STRIDE = 40
VOLATILITY_MIN_LEN = 100
STYLE_TRANSITION_THRESHOLD_MULTIPLIER = 1.2


# ─── 工具函数 ───

def _get_chars(text):
    return [c for c in text if '\u4e00' <= c <= '\u9fff']


def _split_sentences(text):
    text = text.strip()
    if not text:
        return []
    raw = re.split(r'[。！？；\n]+', text)
    return [s.strip() for s in raw if len(s.strip()) >= 2]


def _get_ngrams(chars, n):
    if len(chars) < n:
        return []
    return [''.join(chars[i:i+n]) for i in range(len(chars) - n + 1)]


def _count_colloquial(text):
    count = 0
    for mark in COLLOQUIAL_MARKS:
        if mark in text:
            count += text.count(mark)
    return count


def _entropy(counter, total):
    """计算熵，带零保护"""
    if total <= 0:
        return 0.0
    probs = [c / total for c in counter.values()]
    return -sum(p * math.log2(p) for p in probs if p > 0)


# ─── 风格向量提取 ───

def _style_vector(chars, sentences, raw_text=""):
    if not chars or len(chars) < 5:
        return None

    vec = {}
    total = len(chars)

    # 1. 字频分布熵
    cc = Counter(chars)
    vec["entropy"] = _entropy(cc, total) / 12.3 if total > 0 else 0.0

    # 2. 句长CV
    if sentences and len(sentences) >= 2:
        lens = [len(_get_chars(s)) for s in sentences]
        mean_l = sum(lens) / len(lens)
        if mean_l > 0:
            std_l = math.sqrt(sum((l - mean_l) ** 2 for l in lens) / len(lens))
            vec["sent_cv"] = std_l / mean_l
        else:
            vec["sent_cv"] = 0.0
    else:
        vec["sent_cv"] = 0.0

    # 3. MATTR（窗口150字）
    ws = min(150, total)
    if ws >= 10:
        ttrs = []
        step = max(1, ws // 6)
        for i in range(0, total - ws + 1, step):
            w = chars[i:i+ws]
            ttrs.append(len(set(w)) / len(w))
        vec["mattr"] = sum(ttrs) / len(ttrs) if ttrs else 0.5
    else:
        vec["mattr"] = len(set(chars)) / total if total > 0 else 0.0

    # 4. 四字格重复
    fours = _get_ngrams(chars, 4)
    vec["four_rep"] = 0.0
    if fours:
        fc = Counter(fours)
        repeats = sum(1 for c in fc.values() if c > 1)
        vec["four_rep"] = repeats / len(fours)

    # 5. 文白比
    classical = sum(1 for c in chars if c in CLASSICAL_CHARS)
    vec["wenbai"] = classical / total if total > 0 else 0.0

    # 6. 主语省略率
    if sentences:
        omit = sum(1 for s in sentences if any(re.search(p, s) for p in SUBJECT_OMIT_PATTERNS))
        vec["subject_omit"] = omit / len(sentences)
    else:
        vec["subject_omit"] = 0.0

    # 7. 3-gram重复
    tris = _get_ngrams(chars, 3)
    vec["trigram_rep"] = 0.0
    if tris:
        tc = Counter(tris)
        repeats = sum(1 for c in tc.values() if c > 1)
        vec["trigram_rep"] = repeats / len(tris)

    # 8. 口语标记密度
    if raw_text:
        coll_count = _count_colloquial(raw_text)
        vec["colloquial"] = coll_count / total if total > 0 else 0.0
    else:
        vec["colloquial"] = 0.0

    return vec


def _vector_distance(v1, v2):
    if v1 is None or v2 is None:
        return 0.0
    keys = ["entropy", "sent_cv", "mattr", "four_rep", "wenbai", "subject_omit", "trigram_rep", "colloquial"]
    dot = sum(v1.get(k, 0) * v2.get(k, 0) for k in keys)
    n1 = math.sqrt(sum(v1.get(k, 0) ** 2 for k in keys))
    n2 = math.sqrt(sum(v2.get(k, 0) ** 2 for k in keys))
    if n1 * n2 == 0:
        return 0.0
    return 1 - dot / (n1 * n2)


# ─── 风格断裂检测 ───

def compute_style_transition_score(text):
    chars = _get_chars(text)
    if len(chars) < STYLE_WINDOW * 1.5:
        return 0.0, []

    windows = []
    for i in range(0, len(chars) - STYLE_WINDOW + 1, STYLE_STRIDE):
        window_chars = chars[i:i+STYLE_WINDOW]
        window_text = ''.join(window_chars)
        window_sents = _split_sentences(window_text)
        vec = _style_vector(window_chars, window_sents, window_text)
        if vec:
            windows.append((i, vec))

    if len(windows) < 2:
        return 0.0, []

    distances = []
    for j in range(len(windows) - 1):
        d = _vector_distance(windows[j][1], windows[j+1][1])
        distances.append(d)

    if not distances:
        return 0.0, []

    mean_d = sum(distances) / len(distances)
    std_d = math.sqrt(sum((d - mean_d) ** 2 for d in distances) / len(distances)) if len(distances) > 1 else 0.0
    threshold = mean_d + STYLE_TRANSITION_THRESHOLD_MULTIPLIER * std_d

    fracture_points = []
    for j, d in enumerate(distances):
        if d > threshold and d > 0.15:
            fracture_points.append({
                "position": windows[j][0] + STYLE_WINDOW // 2,
                "distance": round(d, 4),
            })

    max_transition = max(distances) if distances else 0.0
    return max_transition, fracture_points


# ─── Register Volatility ───

def compute_register_volatility(text):
    chars = _get_chars(text)
    if len(chars) < VOLATILITY_MIN_LEN:
        return 0.0

    window_size = 60
    stride = 20
    registers = []

    for i in range(0, len(chars) - window_size + 1, stride):
        w = chars[i:i+window_size]
        classical = sum(1 for c in w if c in CLASSICAL_CHARS)
        colloquial = _count_colloquial(''.join(w))
        total_w = len(w)
        if total_w > 0:
            formal_score = classical / total_w
            coll_score = colloquial / total_w
            registers.append(formal_score - coll_score)

    if len(registers) < 2:
        return 0.0

    mean_r = sum(registers) / len(registers)
    variance = sum((r - mean_r) ** 2 for r in registers) / len(registers)
    volatility = math.sqrt(variance)

    # 归一化到 0-1
    normalized = min(1.0, volatility * 5)
    return normalized


# ─── 特征提取（主函数）───

def extract_features(text):
    if not text or len(text.strip()) < 5:
        return {f"f{i}": 0.0 for i in range(1, 13)}

    chars = _get_chars(text)
    total = len(chars)
    if total < 3:
        return {f"f{i}": 0.0 for i in range(1, 13)}

    sentences = _split_sentences(text)

    # f1: 字频分布熵
    cc = Counter(chars)
    f1 = _entropy(cc, total) / 12.3 if total > 0 else 0.0

    # f2: 句长变异系数
    if sentences and len(sentences) >= 2:
        lens = [len(_get_chars(s)) for s in sentences]
        mean_l = sum(lens) / len(lens)
        if mean_l > 0:
            std_l = math.sqrt(sum((l - mean_l) ** 2 for l in lens) / len(lens))
            f2 = std_l / mean_l
        else:
            f2 = 0.0
    else:
        f2 = 0.0

    # f3: MATTR（窗口150字）
    ws = min(150, total)
    if ws >= 10:
        ttrs = []
        step = max(1, ws // 6)
        for i in range(0, total - ws + 1, step):
            w = chars[i:i+ws]
            ttrs.append(len(set(w)) / len(w))
        f3 = sum(ttrs) / len(ttrs) if ttrs else 0.5
    else:
        f3 = len(set(chars)) / total if total > 0 else 0.0

    # f4: 四字格重复率
    fours = _get_ngrams(chars, 4)
    if fours:
        fc = Counter(fours)
        repeats = sum(1 for c in fc.values() if c > 1)
        f4 = repeats / len(fours)
    else:
        f4 = 0.0

    # f5: 学术套话熵
    cliche_matches = []
    for cliche in ACADEMIC_CLICHES:
        if cliche in text:
            cliche_matches.append(cliche)
    if cliche_matches:
        cc_cliche = Counter(cliche_matches)
        f5 = _entropy(cc_cliche, len(cliche_matches))
    else:
        f5 = 0.0

    # f6: 文白混合度
    classical = sum(1 for c in chars if c in CLASSICAL_CHARS)
    f6 = classical / total if total > 0 else 0.0

    # f7: 标点熵
    puncts = [c for c in text if c in CHINESE_PUNCTUATION]
    if puncts:
        cp = Counter(puncts)
        f7 = _entropy(cp, len(puncts))
    else:
        f7 = 0.0

    # f8: 重复 3-gram 比率
    tris = _get_ngrams(chars, 3)
    if tris:
        tc = Counter(tris)
        repeats = sum(1 for c in tc.values() if c > 1)
        f8 = repeats / len(tris)
    else:
        f8 = 0.0

    # f9: 主语省略率
    if sentences:
        omit = sum(1 for s in sentences if any(re.search(p, s) for p in SUBJECT_OMIT_PATTERNS))
        f9 = omit / len(sentences)
    else:
        f9 = 0.0

    # f10: 连接词重复率
    conj_matches = [c for c in CONJUNCTIONS if c in text]
    if conj_matches:
        f10 = len(conj_matches) / len(CONJUNCTIONS)
    else:
        f10 = 0.0

    # f11: register volatility
    f11 = compute_register_volatility(text)

    # f12: style transition score
    f12, fracture_points = compute_style_transition_score(text)

    return {
        "f1": round(f1, 6),
        "f2": round(f2, 6),
        "f3": round(f3, 6),
        "f4": round(f4, 6),
        "f5": round(f5, 6),
        "f6": round(f6, 6),
        "f7": round(f7, 6),
        "f8": round(f8, 6),
        "f9": round(f9, 6),
        "f10": round(f10, 6),
        "f11": round(f11, 6),
        "f12": round(f12, 6),
    }


# ─── 规则兜底检测 ───

def _rule_based_detect(text, features, is_academic=False):
    """
    基于规则的兜底检测。
    不依赖模型，用特征阈值做判断。
    学术文本使用更宽松的阈值（学术写作本身就有很多套话）。
    返回 (label, confidence, score, reasons)
    """
    score = 0.0
    reasons = []
    total = len(_get_chars(text))

    if total < 5:
        return 0, 0.0, 0.0, ["文本太短"]

    # 学术文本的套话阈值要高很多，因为人类写的学术论文也有大量套话
    cliche_threshold_high = 4.0 if is_academic else 1.5
    cliche_threshold_mid = 2.0 if is_academic else 0.5
    cliche_threshold_low = 0.8 if is_academic else 0.0

    # 1. 学术套话熵高 → AI
    if features["f5"] > cliche_threshold_high:
        score += 0.25
        reasons.append("学术套话丰富")
    elif features["f5"] > cliche_threshold_mid:
        score += 0.15
        reasons.append("学术套话较多")
    elif features["f5"] > cliche_threshold_low:
        score += 0.08

    # 2. 字频分布熵低 → 用字单调 → AI
    if features["f1"] < 0.6:
        score += 0.1
        reasons.append("用字单调")

    # 3. 句长变异系数低 → 句式规整 → AI（学术文本阈值放宽）
    sent_cv_low = 0.3 if is_academic else 0.4
    if 0 < features["f2"] < sent_cv_low:
        score += 0.1
        reasons.append("句式规整")
    elif features["f2"] > 0.8:
        score -= 0.05  # 句长变化大 → 人类

    # 4. MATTR 低 → 词汇丰富度低 → AI
    if 0 < features["f3"] < 0.5:
        score += 0.08
        reasons.append("词汇丰富度低")

    # 5. 四字格重复率高 → AI
    if features["f4"] > 0.08:
        score += 0.08
        reasons.append("四字格重复")

    # 6. 文白混合度极低 → 无文言 → AI
    if features["f6"] < 0.01:
        score += 0.05

    # 7. 标点熵低 → 标点使用单一 → AI
    if 0 < features["f7"] < 1.5:
        score += 0.05

    # 8. 3-gram重复率高 → AI
    if features["f8"] > 0.2:
        score += 0.08
        reasons.append("短语重复")

    # 9. 主语省略率高 → AI
    if features["f9"] > 0.5:
        score += 0.08
        reasons.append("主语省略频繁")

    # 10. 连接词重复率低 → AI
    if features["f10"] < 0.05:
        score += 0.05

    # 11. register volatility 低 → 语域稳定 → AI
    if 0 < features["f11"] < 0.05 and total >= VOLATILITY_MIN_LEN:
        score += 0.08
        reasons.append("语域过于稳定")

    # 12. style transition score 高 → 混写 → AI
    if features["f12"] > 0.3:
        score += 0.15
        reasons.append("风格断裂")

    # 口语标记 → 人类
    coll_count = _count_colloquial(text)
    if coll_count >= 2:
        score -= 0.1
    elif coll_count >= 1:
        score -= 0.05

    # 文本太短惩罚
    if total < 20:
        score *= 0.7

    # 学术文本整体降权：学术写作本身就"像AI"
    if is_academic:
        score *= 0.7

    # 阈值 0.2
    label = 1 if score >= 0.2 else 0
    confidence = min(0.9, max(0.5, 0.5 + score))
    # 如果分数很低，置信度也低
    if score < 0.1:
        confidence = 0.3 + score

    return label, round(confidence, 4), round(score, 4), reasons


# ─── 加载模型 ───

def _load_model():
    if os.path.exists(MODEL_PATH):
        try:
            with open(MODEL_PATH, 'rb') as f:
                model = pickle.load(f)
            return model
        except Exception:
            return None
    return None


# ─── 主检测函数 ───

def detect_aigc(text):
    if not text or len(text.strip()) < 3:
        return {
            "label": 0,
            "confidence": 0.0,
            "probability": 0.0,
            "details": {
                "text_length": len(text) if text else 0,
                "char_count": 0,
                "fracture_points": [],
                "register_volatility": 0.0,
                "rule_score": 0.0,
                "reasons": ["文本太短"],
                "segments": [],
            },
            "features": {f"f{i}": 0.0 for i in range(1, 13)},
        }

    # 预处理：清理OCR噪音、引用标记
    original_len = len(text)
    text = _preprocess_text(text)
    is_academic = _is_academic_text(text)
    total = len(_get_chars(text))

    # 分段检测：按段落切分，每段独立检测
    paragraphs = re.split(r'\n+', text)
    paragraphs = [p.strip() for p in paragraphs if len(_get_chars(p)) >= 10]

    if len(paragraphs) < 2:
        # 段落太少，不切分，直接整篇检测
        return _detect_single(text, original_len, is_academic)

    # 每段单独检测，按字符数加权汇总
    segment_results = []
    weighted_prob = 0.0
    weighted_rule = 0.0
    total_weight = 0
    all_reasons = set()

    for para in paragraphs:
        seg_chars = len(_get_chars(para))
        if seg_chars < 10:
            continue
        seg_result = _detect_single(para, len(para), is_academic)
        weight = seg_chars
        weighted_prob += seg_result["probability"] * weight
        weighted_rule += seg_result["details"]["rule_score"] * weight
        total_weight += weight
        all_reasons.update(seg_result["details"]["reasons"])
        segment_results.append({
            "chars": seg_chars,
            "probability": round(seg_result["probability"], 4),
            "rule_score": round(seg_result["details"]["rule_score"], 4),
            "label": seg_result["label"],
        })

    if total_weight == 0:
        return _detect_single(text, original_len, is_academic)

    final_prob = weighted_prob / total_weight
    final_rule = weighted_rule / total_weight

    # 判定：概率 > 0.5 为 AI
    final_label = 1 if final_prob > 0.5 else 0
    final_confidence = abs(final_prob - 0.5) * 2  # 映射到 0-1
    final_confidence = min(0.95, max(0.1, 0.5 + final_confidence * 0.45))

    # 全文特征（用于展示）
    features = extract_features(text)
    rv = compute_register_volatility(text)
    _, fracture_points = compute_style_transition_score(text)

    return {
        "label": int(final_label),
        "confidence": float(round(final_confidence, 4)),
        "probability": float(round(final_prob, 4)),
        "details": {
            "text_length": original_len,
            "char_count": total,
            "is_academic": is_academic,
            "segment_count": len(segment_results),
            "segments": segment_results[:10],  # 最多展示10段
            "fracture_points": fracture_points,
            "register_volatility": round(rv, 4),
            "rule_score": round(final_rule, 4),
            "reasons": list(all_reasons),
        },
        "features": features,
    }


def _detect_single(text, original_len, is_academic):
    """单段/单篇检测逻辑"""
    features = extract_features(text)
    total = len(_get_chars(text))

    # 规则兜底
    rule_label, rule_conf, rule_score, reasons = _rule_based_detect(text, features, is_academic)

    # 尝试用 XGBoost 模型
    model = _load_model()
    if model is not None:
        try:
            import numpy as np
            feature_vector = np.array([[features[f"f{i}"] for i in range(1, 13)]])
            model_label = int(model.predict(feature_vector)[0])
            model_proba = float(model.predict_proba(feature_vector)[0, 1])

            # 融合逻辑：
            # 学术文本：模型对学术写作天然偏见，降低模型权重
            # 非学术文本：模型权重较高
            if is_academic:
                # 学术文本：模型权重50%，规则50%，且给模型一个"学术折扣"
                # 把模型概率往0.5方向拉（学术文本本身就像AI）
                adjusted_proba = 0.5 + (model_proba - 0.5) * 0.5
                if abs(adjusted_proba - 0.5) > 0.1:
                    final_label = 1 if adjusted_proba > 0.5 else 0
                    final_confidence = 0.5 * adjusted_proba + 0.5 * rule_conf
                else:
                    final_label = rule_label
                    final_confidence = 0.4 * adjusted_proba + 0.6 * rule_conf
            else:
                # 非学术文本：模型权重70%
                if abs(model_proba - 0.5) > 0.15:
                    final_label = model_label
                    final_confidence = 0.7 * model_proba + 0.3 * rule_conf
                else:
                    final_label = rule_label
                    final_confidence = 0.4 * model_proba + 0.6 * rule_conf

            # 如果规则和模型一致，小幅提高置信度
            if model_label == rule_label:
                final_confidence = min(0.95, final_confidence + 0.03)

            probability = model_proba
        except Exception:
            final_label = rule_label
            final_confidence = rule_conf
            probability = rule_conf
    else:
        final_label = rule_label
        final_confidence = rule_conf
        probability = rule_conf

    rv = compute_register_volatility(text)
    _, fracture_points = compute_style_transition_score(text)

    return {
        "label": int(final_label),
        "confidence": float(round(final_confidence, 4)),
        "probability": float(round(probability, 4)),
        "details": {
            "text_length": original_len,
            "char_count": total,
            "is_academic": is_academic,
            "fracture_points": fracture_points,
            "register_volatility": round(rv, 4),
            "rule_score": rule_score,
            "reasons": reasons,
        },
        "features": features,
    }


# ─── Hedera 插件接口 ───

if _HAS_HEDERA:

    class AIGCDetectorPlugin(PluginBase):
        """AIGC 检测插件 — 中文学术论文 AI 生成内容检测"""

        @property
        def plugin_name(self):
            return "AIGC检测"

        @property
        def plugin_version(self):
            return "3.1.0"

        def match(self, text):
            text_lower = text.lower()
            keywords = ["aigc", "ai生成", "查ai", "检测ai", "论文检测", "查重"]
            return any(kw in text_lower for kw in keywords)

        def process(self, text, **kwargs):
            result = detect_aigc(text)
            return self._format_response(result)

        def _format_response(self, result):
            label_text = "AI生成" if result["label"] == 1 else "人类写作"
            confidence = result["confidence"]

            response = f"【AIGC 检测结果】\n"
            response += f"判断：{label_text}，置信度：{confidence:.2%}\n"
            response += f"文本长度：{result['details']['text_length']}字符\n"
            response += f"中文字数：{result['details']['char_count']}\n"

            if result['details']['register_volatility'] > 0:
                response += f"语域波动：{result['details']['register_volatility']:.4f}\n"

            fracture = result['details'].get('fracture_points', [])
            if fracture:
                response += f"风格断裂点：{len(fracture)}处\n"

            if 'reasons' in result['details']:
                response += f"依据：{'；'.join(result['details']['reasons'])}\n"

            response += "\n【特征明细】\n"
            feature_names = [
                "字频分布熵", "句长变异系数", "字级MATTR", "四字格重复率",
                "学术套话熵", "文白混合度", "标点熵", "重复3-gram比率",
                "主语省略率", "连接词重复率", "语域波动", "风格断裂分",
            ]
            for i, name in enumerate(feature_names):
                val = result['features'].get(f"f{i+1}", 0)
                response += f"  {name}: {val:.4f}\n"

            return response

        def get_tools(self):
            return {
                "detect_aigc": {
                    "description": "检测文本是否为AI生成",
                    "handler": self._tool_detect,
                    "parameters": {
                        "text": {"type": "string", "description": "待检测文本"}
                    }
                }
            }

        def _tool_detect(self, text):
            result = detect_aigc(text)
            return {
                "label": "AI" if result["label"] == 1 else "Human",
                "confidence": result["confidence"],
                "details": result["details"],
            }

else:
    # 没有 Hedera 框架时，提供一个占位类
    class AIGCDetectorPlugin:
        pass
