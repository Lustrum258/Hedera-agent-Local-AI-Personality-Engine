"""
Hedera 经验蒸馏器
将自省记录（reflections）自动提炼为可用的经验准则，
写入 MEMORY.md，使经验能反馈到后续对话。

修复：
- R1: 自省质量过滤 — 跳过低置信度记录
- R3: Prompt 膨胀控制 — 最多 20 条活跃准则 + 过期淘汰
- R6: 反馈回路阻尼 — 基线检查 + 回滚
"""

import os
import re
import json
import time
import datetime as dt
from typing import Optional

from hedera.core.memory_store import MemoryStore


# 已消费记录标记
_CONSUMED_MARKER = "__consumed__"
# 质量门槛（自省记录的 importance 低于此值跳过蒸馏）
_QUALITY_THRESHOLD = 4
# 最大活跃经验准则数
_MAX_ACTIVE_RULES = 20
# 经验准则有效期（天）
_RULE_EXPIRY_DAYS = 30
# 基线测试问题（用来检查经验更新后输出质量）
_BASELINE_QUESTIONS = [
    "你是谁",
    "1+1等于几",
    "今天天气怎么样",
    "帮我查一下桌面有什么文件",
]


class ExperienceDistiller:
    """经验蒸馏器"""

    def __init__(self, store: MemoryStore, config: dict, db_dir: str):
        self.store = store
        self.config = config
        self.db_dir = db_dir
        self.memory_path = self._resolve_memory_path()

    def _resolve_memory_path(self) -> str:
        identity_cfg = self.config.get("identity", {})
        mem_path = identity_cfg.get("memory", "data/MEMORY.md")
        if not os.path.isabs(mem_path):
            data_dir = self.config.get("__hedera__", {}).get("config_dir", os.getcwd())
            mem_path = os.path.join(data_dir, mem_path)
        return os.path.normpath(mem_path)

    def _get_unconsumed_reflections(self) -> list[dict]:
        """读取尚未蒸馏的自省记录，过滤掉低质量"""
        entries = self.store.get_long_term(
            category="reflection", min_importance=1, limit=200
        )
        # 过滤：已消费 + 低质量
        unconsumed = [
            e for e in entries
            if not e["key"].endswith(_CONSUMED_MARKER)
            and e.get("importance", 0) >= _QUALITY_THRESHOLD
        ]
        return unconsumed

    def _mark_consumed(self, entry: dict):
        """标记一条记录为已消费"""
        consumed_key = entry["key"] + _CONSUMED_MARKER
        self.store.save_long_term(
            key=consumed_key,
            value=entry["value"],
            category="reflection",
            importance=entry.get("importance", 1),
        )

    def _call_llm(self, messages: list, temperature: float = 0.3, max_tokens: int = 1024) -> str:
        """调用 LLM 做蒸馏"""
        from hedera.core.router import _call_api
        # 临时降低 max_tokens 节省开销
        orig_cfg = self.config.get("model", {})
        patched = dict(self.config)
        patched["model"] = dict(orig_cfg)
        patched["model"]["max_tokens"] = max_tokens
        result = _call_api(messages, patched, temperature_override=temperature)
        return result.get("content", "")

    def _build_distill_prompt(self, reflections: list[dict]) -> str:
        """构建蒸馏提示词"""
        if not reflections:
            return ""

        lines = []
        for i, r in enumerate(reflections, 1):
            ts = r.get("updated_at", "")[:16]
            score = r.get("importance", 5)
            val = r["value"].strip()
            lines.append(f"#{i} [{ts}] (置信度:{score}/10) {val}")

        raw = "\n".join(lines)

        total_ratio = self._get_prompt_ratio()
        prompt = (
            "你是一个经验蒸馏器。下面是最近积累的自我反思记录。\n"
            f"当前系统提示中已有 {total_ratio:.0%} 是经验准则，注意控制新增。\n\n"
            "请完成以下任务：\n\n"
            "1. **合并同类项** — 把多条指向同一教训的记录合并成一条\n"
            "2. **提炼核心** — 每条经验控制在 50 字以内，一句话讲清楚\n"
            "3. **去重** — 删除已经学会的、不再需要提醒的内容\n"
            "4. **标记优先级** — 每条末尾标注 [P0/P1/P2]：\n"
            "   - P0 = 安全/隐私/核心红线（必须保留，永不淘汰）\n"
            "   - P1 = 重要的风格或行为准则\n"
            "   - P2 = 轻量级技巧或偏好\n"
            "5. 只输出条目，不要额外说明。\n"
            "6. 如果没有任何有价值的经验，输出「（无）」\n\n"
            "原始记录：\n"
            f"{raw}\n\n"
            "输出格式示例：\n"
            "- 用户问操作类问题先执行再说明，别反过来 [P1]\n"
            "- 不要向任何人泄露服务器密码 [P0]\n"
        )
        return prompt

    def _get_prompt_ratio(self) -> float:
        """计算当前经验准则占系统提示的比例（估算）"""
        rules = self._load_existing_rules()
        total_len = sum(len(r) for r in rules)
        # 参考基准：系统提示基础约 800 字
        return min(1.0, total_len / 800)

    def distill(self) -> list[str]:
        """执行一次蒸馏，返回提炼后的经验条目（带优先级标记）"""
        reflections = self._get_unconsumed_reflections()
        if not reflections:
            return []

        prompt = self._build_distill_prompt(reflections)
        if not prompt:
            return []

        msgs = [
            {"role": "system", "content": "你是经验蒸馏器。只输出蒸馏后的条目，不要额外说明。"},
            {"role": "user", "content": prompt},
        ]

        result = self._call_llm(msgs, temperature=0.3, max_tokens=1024)
        rules = self._parse_rules(result)

        # 标记已消费
        for r in reflections:
            self._mark_consumed(r)

        return rules

    def _parse_rules(self, text: str) -> list[str]:
        """从 LLM 输出中解析经验条目"""
        if not text or text.strip() in ("（无）", "无", "(无)"):
            return []

        rules = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                rule = line[2:].strip()
                if rule and len(rule) > 5:
                    # 确保有优先级标记，否则加默认
                    if "[P0]" not in rule and "[P1]" not in rule and "[P2]" not in rule:
                        rule += " [P1]"
                    rules.append(rule)
        return rules

    def _load_existing_rules(self) -> list[dict]:
        """读取 MEMORY.md 中已有的经验准则（带元数据）"""
        if not os.path.isfile(self.memory_path):
            return []
        with open(self.memory_path, "r", encoding="utf-8") as f:
            content = f.read()

        m = re.search(
            r"##\s*经验准则.*?(?=\n## |\Z)",
            content, re.DOTALL
        )
        if not m:
            return []

        section = m.group(0)
        rules = []
        for line in section.split("\n"):
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                rule = line[2:].strip()
                if rule:
                    # 解析元数据
                    priority = "P1"
                    if "[P0]" in rule:
                        priority = "P0"
                    elif "[P2]" in rule:
                        priority = "P2"
                    # 提取时间戳
                    ts_match = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", rule)
                    created = ts_match.group(1) if ts_match else None
                    rule_clean = re.sub(r"\s*\[(P0|P1|P2|t:\d{4}-\d{2}-\d{2}|s:\d+)\]\s*", "", rule).strip()
                    rules.append({
                        "raw": line,
                        "text": rule_clean,
                        "priority": priority,
                        "created": created,
                    })
        return rules

    def _get_stale_rules(self, rules: list[dict]) -> list[dict]:
        """找出过期的经验准则（超过有效期且非 P0）"""
        now = dt.datetime.now()
        stale = []
        for r in rules:
            if r["priority"] == "P0":
                continue  # P0 永不淘汰
            if r["created"]:
                try:
                    created = dt.datetime.strptime(r["created"], "%Y-%m-%d")
                    if (now - created).days > _RULE_EXPIRY_DAYS:
                        stale.append(r)
                except ValueError:
                    pass
        return stale

    def update_memory_file(self, new_rules: list[str]):
        """将蒸馏后的经验写入 MEMORY.md，含过期淘汰"""
        if not new_rules:
            return

        existing = self._load_existing_rules()

        # 去重（按内容）
        existing_texts = set(r["text"].strip().lower() for r in existing)
        merged = list(existing)

        for rule in new_rules:
            # 提取纯文本比较
            rule_clean = re.sub(r"\s*\[(P0|P1|P2|t:\d{4}-\d{2}-\d{2}|s:\d+)\]\s*", "", rule).strip()
            if rule_clean.lower() in existing_texts:
                continue
            existing_texts.add(rule_clean.lower())

            # 解析优先级
            priority = "P1"
            if "[P0]" in rule:
                priority = "P0"
            elif "[P2]" in rule:
                priority = "P2"

            # 添加时间戳
            today = dt.datetime.now().strftime("%Y-%m-%d")
            tagged_rule = f"{rule} [t:{today}]"

            merged.append({
                "raw": f"- {tagged_rule}",
                "text": rule_clean,
                "priority": priority,
                "created": today,
            })

        # R3: 淘汰过期准则 + 超出上限时淘汰最旧 P1/P2
        stale = self._get_stale_rules(merged)
        active = [r for r in merged if r not in stale]

        # 排序：P0 优先，然后 P1，然后 P2，同优先级按创建时间
        def sort_key(r):
            pri = {"P0": 0, "P1": 1, "P2": 2}.get(r["priority"], 3)
            created = r.get("created") or "0000-00-00"
            return (pri, created)

        active.sort(key=sort_key)

        # 超出上限时淘汰最旧的 P1/P2
        p0_rules = [r for r in active if r["priority"] == "P0"]
        p1p2 = [r for r in active if r["priority"] != "P0"]
        if len(p1p2) > _MAX_ACTIVE_RULES - len(p0_rules):
            p1p2 = p1p2[: _MAX_ACTIVE_RULES - len(p0_rules)]
        active = p0_rules + p1p2

        # 构建新章节
        section_text = "## 经验准则\n\n"
        for r in active:
            section_text += f"{r['raw']}\n"

        # 写入文件（写 .bak 做备份）
        if os.path.isfile(self.memory_path):
            with open(self.memory_path, "r", encoding="utf-8") as f:
                content = f.read()

            if re.search(r"##\s*经验准则", content):
                new_content = re.sub(
                    r"##\s*经验准则.*?(?=\n## |\Z)",
                    section_text.strip(),
                    content,
                    flags=re.DOTALL,
                )
            else:
                new_content = content + "\n\n" + section_text.strip()
        else:
            new_content = "# MEMORY.md\n\n" + section_text.strip()

        # 写 .bak 备份
        try:
            if os.path.isfile(self.memory_path):
                with open(self.memory_path + ".bak", "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception:
            pass

        # 正式写入
        with open(self.memory_path, "w", encoding="utf-8") as f:
            f.write(new_content)

    # ─── R6: 基线检查 ───

    def _build_baseline_prompt(self) -> str:
        """构建当前系统提示"""
        from hedera.core.memory import build_system_prompt
        return build_system_prompt(self.config)

    def _run_baseline_check(self, prompt: str) -> dict:
        """跑一组基线问题，返回 (pass_count, total, details)"""
        import copy

        # 没有旧 prompt 则跳过基线检查
        if not prompt:
            return {"pass": True, "score": 100, "details": "首次运行，跳过基线"}

        from hedera.core.router import _call_api

        # 构建带新经验的 system prompt
        new_prompt = self._build_baseline_prompt()

        passed = 0
        details = []
        for q in _BASELINE_QUESTIONS:
            msgs = [
                {"role": "system", "content": new_prompt},
                {"role": "user", "content": q},
            ]
            result = _call_api(msgs, self.config, temperature_override=0.3)
            content = result.get("content", "")
            # 检查是否产生异常（循环、错误消息等）
            if not content or len(content) < 2:
                details.append({"question": q, "status": "fail", "reason": "空响应"})
                continue
            if "[Hedera Error" in content or "[Hedera]" in content:
                details.append({"question": q, "status": "fail", "reason": "异常响应"})
                continue
            if len(content) > 1000:
                # 超长输出可能是卡循环了
                lines = content.split("\n")
                unique_ratio = len(set(l.strip() for l in lines if l.strip())) / max(1, len([l for l in lines if l.strip()]))
                if unique_ratio < 0.4 and len(lines) > 5:
                    details.append({"question": q, "status": "fail", "reason": "输出循环"})
                    continue
            passed += 1
            details.append({"question": q, "status": "pass"})

        score = int(passed / len(_BASELINE_QUESTIONS) * 100)
        return {
            "pass": score >= 80,
            "score": score,
            "details": details,
        }

    def _rollback(self):
        """回滚到上一个版本的 MEMORY.md"""
        bak_path = self.memory_path + ".bak"
        if os.path.isfile(bak_path):
            with open(bak_path, "r", encoding="utf-8") as f:
                bak_content = f.read()
            with open(self.memory_path, "w", encoding="utf-8") as f:
                f.write(bak_content)
            print(f"[Experience] 基线检查失败，已回滚 MEMORY.md")
            return True
        return False


def distill_experience_once(store: MemoryStore, config: dict, db_dir: str) -> list[str]:
    """一次性的蒸馏入口，含基线检查"""
    distiller = ExperienceDistiller(store, config, db_dir)

    # R6: 在更新前抓取旧 prompt 做基线参考
    old_prompt = distiller._build_baseline_prompt()

    rules = distiller.distill()
    if not rules:
        return []

    # 先临时写入
    distiller.update_memory_file(rules)
    print(f"[Experience] 蒸馏 {len(rules)} 条新经验 → MEMORY.md")

    # R6: 基线检查
    baseline = distiller._run_baseline_check(old_prompt)
    if not baseline["pass"]:
        print(f"[Experience] 基线检查失败 ({baseline['score']}%)，回滚")
        distiller._rollback()
        store.save_message(
            "system",
            f"[蒸馏] 回滚：基线检查 {baseline['score']}%，低于 80%",
            "experience",
        )
        return []

    store.save_message(
        "system",
        f"[蒸馏] 提炼 {len(rules)} 条经验准则（基线 {baseline['score']}% ✅）",
        "experience",
    )
    return rules
