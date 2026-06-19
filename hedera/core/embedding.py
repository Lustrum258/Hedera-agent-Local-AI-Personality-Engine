"""
Hedera 轻量级向量记忆检索
纯 Python 实现，零外部依赖。
使用字符 n-gram + 哈希 trick 生成固定维度的稀疏向量，
再通过余弦相似度检索。对中英文均有效。
"""

import hashlib
import math
import re
import struct
from typing import Optional

# 向量维度（哈希桶数）
DIM = 4096


def _tokenize(text: str) -> list[str]:
    """分词：中文按字符 bigram，英文按空格+小写。"""
    text = text.lower().strip()
    tokens = []
    # 中文字符 bigram
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    for i in range(len(chinese_chars) - 1):
        tokens.append(chinese_chars[i] + chinese_chars[i + 1])
    # 单字也加入
    tokens.extend(chinese_chars)
    # 英文单词
    english_words = re.findall(r'[a-z_][a-z0-9_]{1,}', text)
    tokens.extend(english_words)
    return tokens


def _hash_token(token: str) -> tuple[int, int]:
    """将 token 哈希到 (index, sign)，index ∈ [0, DIM)，sign ∈ {-1, +1}。"""
    h = hashlib.md5(token.encode("utf-8")).digest()
    idx = struct.unpack("<I", h[:4])[0] % DIM
    sign = 1 if h[4] & 1 else -1
    return idx, sign


def embed(text: str) -> list[float]:
    """将文本转为 DIM 维浮点向量（L2 归一化）。"""
    tokens = _tokenize(text)
    if not tokens:
        return [0.0] * DIM
    vec = [0.0] * DIM
    # TF 权重：log(1 + count)
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    for t, count in tf.items():
        idx, sign = _hash_token(t)
        weight = math.log(1 + count)
        vec[idx] += sign * weight
    # L2 归一化
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度（向量已 L2 归一化时等价于点积）。"""
    return sum(x * y for x, y in zip(a, b))


def pack_vector(vec: list[float]) -> bytes:
    """将浮点向量打包为 bytes（4 字节 float × DIM）。"""
    return struct.pack(f"<{DIM}f", *vec)


def unpack_vector(data: bytes) -> list[float]:
    """将 bytes 解包为浮点向量。"""
    return list(struct.unpack(f"<{DIM}f", data))
