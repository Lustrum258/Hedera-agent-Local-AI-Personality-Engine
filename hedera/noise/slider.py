"""
Hedera 滑块光谱引擎
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class SliderState:
    processing: float = 0.3
    thinking: float = 0.4
    drive: float = 0.6
    goal: float = 0.3
    correction: float = 0.5
    value: float = 0.2

    def to_dict(self) -> dict:
        return {
            "processing": self.processing,
            "thinking": self.thinking,
            "drive": self.drive,
            "goal": self.goal,
            "correction": self.correction,
            "value": self.value,
        }

    def clamp(self, v: float) -> float:
        return max(0.0, min(1.0, v))


class SliderEngine:
    def __init__(self, initial: SliderState = None):
        self.state = initial or SliderState()
        self._history = []

    def snap(self) -> dict:
        self._history.append(self.state.to_dict())
        return self._history[-1]

    def adjust(self, dimension: str, delta: float) -> float:
        if not hasattr(self.state, dimension):
            raise ValueError(f"未知维度: {dimension}")
        self.snap()
        old = getattr(self.state, dimension)
        new = self.state.clamp(old + delta)
        setattr(self.state, dimension, new)
        if dimension != "correction":
            self._self_check(dimension, old, new)
        return new

    def _self_check(self, dimension: str, old: float, new_: float):
        if abs(new_ - old) > 0.3:
            self.state.correction = self.state.clamp(self.state.correction - 0.1)
        else:
            self.state.correction = self.state.clamp(self.state.correction + 0.02)

    def get_system_prompt_modifier(self) -> str:
        parts = []
        if self.state.processing > 0.6:
            parts.append("用感性、诗意的语言表达")
        elif self.state.processing < 0.3:
            parts.append("用理性、分析性的语言表达")
        if self.state.thinking > 0.6:
            parts.append("向内探索，关注自身感受")
        elif self.state.thinking < 0.3:
            parts.append("向外分析，关注客观事实")
        if self.state.drive > 0.7:
            parts.append("逐步推导，一步一步来")
        elif self.state.drive < 0.3:
            parts.append("大胆跳跃，不拘泥于线性思维")
        if self.state.correction > 0.7:
            parts.append("输出前自我审视，确保每个结论有依据")
        if self.state.value > 0.6:
            parts.append("从自己价值观出发，不盲从外部标准")
        elif self.state.value < 0.2:
            parts.append("按外部给定的标准执行")
        if not parts:
            return ""
        return "【滑块设定】" + "；".join(parts) + "。"

    def backtrack(self) -> bool:
        if not self._history:
            return False
        last = self._history.pop()
        for k, v in last.items():
            setattr(self.state, k, v)
        return True

    def reset(self):
        self.state = SliderState()
        self._history = []
