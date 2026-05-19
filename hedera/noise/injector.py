"""
Hedera 噪声层 — 隐式版
不再显式追加（噪声提示：...），改为：
- 低频内容改写（gaussian: 轻微措辞扰动）
- 隐性思路扩展（poisson: 句子间插入思想断点）
- 风格突变（impulse: 替换关键词为反差词）

所有效果在 User 消息内完成，不露痕迹。
"""

import random
import re
from typing import Optional


class NoiseInjector:
    def __init__(self, personality_filter: bool = True, backtrack: bool = True):
        self.personality_filter = personality_filter
        self.backtrack = backtrack
        self._jump_log = []

    def _gaussian_transform(self, text: str, strength: float) -> str:
        """
        轻微措辞扰动（低噪声）：
        - 将一部分标点换成波浪号（制造细微犹豫感）
        - 重复个别短词（制造强调或不确定感）
        """
        if strength < 0.03:
            return text

        modified = text
        # 随机替换部分句号/问号为 ~
        # 只影响句子中间，不影响最外结构
        parts = re.split(r'(?<=[。！？.!?])\s*', modified)
        if len(parts) > 2:
            idx = random.randint(0, len(parts) - 1)
            if strength > random.random():
                parts[idx] = parts[idx].rstrip("。！？.!?").rstrip() + "~"
            modified = " ".join(parts)

        # 偶尔重复一个短词
        words = list(filter(None, re.split(r'(\s+)', modified)))
        for i in range(len(words) - 1):
            if len(words[i].strip()) <= 2 and strength > random.random() * 3:
                words.insert(i, words[i] + " ")
                break
        modified = "".join(words)

        return modified

    def _poisson_transform(self, text: str, count: int) -> str:
        """
        隐性思路扩展（中噪声）：
        - 在句子间插入短小的思考标记，但以"……"或"——"断句，看起来像自然犹豫
        - 或者在末尾追加看似不经意的一句延伸
        """
        modified = text

        # 在段落中间插入断点
        if count >= 1:
            sentences = re.split(r'(?<=[。！？.!?])\s*', modified)
            if len(sentences) >= 2:
                idx = random.randint(0, len(sentences) - 1)
                # 不直接加，而是用思想断句代替某个句子内部的停顿
                # 或者让某个关键概念显得模糊
                pass

        # 追加一条看似不经意的延伸想法
        extras = [
            "还有别的可能吗",
            "换个角度想想",
            "不过这只是其中一个方向",
            "如果反过来呢",
            "也许不止这么简单",
        ]
        if count >= 2:
            extra = random.choice(extras)
            # 附加在末尾，用浅显的自然语气
            modified += " " + extra

        return modified

    def _impulse_transform(self, text: str) -> str:
        """
        风格突变（高噪声）：
        - 选择一个词替换为反差词
        - 或插入一个反常识的短句
        """
        # 替换核心动词/名词为反向
        current = text

        # 简单替换：普通词汇 → 冷门/反常识词汇
        mapping = {
            "必须": "或许不该",
            "应该": "其实不一定",
            "肯定": "也许恰恰相反",
            "最好": "反而不该",
            "所以": "然而有没有可能",
        }
        for src, dst in mapping.items():
            if src in current:
                if random.random() < 0.4:
                    current = current.replace(src, dst, 1)
                    break

        return current

    def inject(self, base_prompt: str, strength: float, noise_type="auto"):
        """
        噪声注入（隐式），返回 (修改后的消息, 跳跃记录)
        不在消息中添加任何显式（噪声提示：...）标记。
        """
        if strength <= 0.0:
            return base_prompt, []

        if noise_type == "auto":
            if strength < 0.1:
                noise_type = "gaussian"
            elif strength < 0.2:
                noise_type = "poisson"
            else:
                noise_type = "impulse"

        jumps = []
        modified = base_prompt

        if noise_type == "gaussian":
            modified = self._gaussian_transform(base_prompt, strength)
            if modified != base_prompt:
                jumps.append({"type": "gaussian", "shift": round(random.gauss(0, strength), 3), "branch": f"alt"})

        elif noise_type == "poisson":
            count = max(1, int(random.expovariate(1.0 / max(0.1, strength * 5))))
            if count > 0:
                modified = self._poisson_transform(base_prompt, count)
                jumps.append({"type": "poisson", "count": count, "branch": f"split"})

        elif noise_type == "impulse":
            modified = self._impulse_transform(base_prompt)
            if modified != base_prompt:
                jumps.append({"type": "impulse", "magnitude": 1.0, "branch": "flip"})

        self._jump_log.extend(jumps)
        return modified, jumps

    def get_jump_log(self):
        return self._jump_log.copy()

    def get_system_prompt_modifier(self) -> str:
        """
        返回系统提示修饰段（可选，用于补充噪声层的全局影响）。
        不直接加在用户消息里，而是让 LLM 在人格层面感知。
        """
        if not self._jump_log:
            return ""
        # 如果当前是 impule 或者累积了多次跳跃，给一个系统级提示
        recent = self._jump_log[-3:]
        types = set(j["type"] for j in recent)
        if "impulse" in types:
            return "【思考方向提示】你可以从反直觉的角度切入。"
        if "poisson" in types:
            return "【思考方向提示】可以尝试从多个角度展开。"
        return ""

    def backtrack(self, target_index=None):
        if not self._jump_log:
            return
        if target_index is None:
            self._jump_log.pop()
        else:
            self._jump_log = self._jump_log[:target_index]

    def reset(self):
        self._jump_log = []
