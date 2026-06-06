"""
热梗学习器 — 自动从网络获取热梗并更新词库
每周运行一次，保持词库新鲜
"""

import os
import json
import time
import yaml
import re
from datetime import datetime, timedelta
from typing import Optional

# 热梗来源配置
MEME_SOURCES = {
    "weibo_hot": "https://weibo.com/ajax/side/hotSearch",
    "bilibili_hot": "https://api.bilibili.com/x/web-interface/search/square?limit=10",
    "douyin_hot": "https://www.douyin.com/aweme/v1/web/hot/search/list/",
}

# 词库路径
VOCAB_DIR = "data/vocabulary"
MEMES_FILE = os.path.join(VOCAB_DIR, "memes.yaml")
SLANG_FILE = os.path.join(VOCAB_DIR, "slang.yaml")
LEARNED_FILE = os.path.join(VOCAB_DIR, "learned.yaml")


def _load_yaml(path: str) -> dict:
    """加载 YAML 文件"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _save_yaml(path: str, data: dict):
    """保存 YAML 文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def _fetch_trending_memes() -> list[dict]:
    """
    从网络获取热梗（示例实现）
    实际使用时需要对接真实的 API
    """
    memes = []

    # 这里可以对接各种热梗 API
    # 示例：从本地缓存读取
    cache_file = os.path.join(VOCAB_DIR, ".meme_cache.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
                # 检查缓存是否过期（7天）
                if time.time() - cached.get("timestamp", 0) < 7 * 24 * 3600:
                    memes = cached.get("memes", [])
        except Exception:
            pass

    return memes


def _generate_responses(meme_text: str, llm_fn=None) -> list[str]:
    """
    为新梗生成回应
    如果有 LLM 函数，用 LLM 生成；否则用模板
    """
    if llm_fn:
        try:
            prompt = f"""为这个网络热梗生成2-3个简短回应，用嚣张、自信的风格：

梗：{meme_text}

要求：
- 回应要简短有力（10字以内）
- 可以用"我chovy"句式
- 保持冬青的人格风格（嚣张、直接、带点混蛋气质）
- 不要解释梗的含义

输出格式（每行一个）：
回应1
回应2
回应3"""

            result = llm_fn(prompt)
            if result:
                responses = [r.strip() for r in result.split("\n") if r.strip()]
                return responses[:3]
        except Exception:
            pass

    # 默认模板回应
    return ["嗯。", "行。", "知道了。"]


def learn_meme(meme_text: str, trigger_words: list[str], llm_fn=None) -> bool:
    """
    学习一个新梗并更新词库

    Args:
        meme_text: 梗的描述
        trigger_words: 触发词列表
        llm_fn: LLM 生成函数（可选）

    Returns:
        是否成功添加
    """
    if not trigger_words:
        return False

    # 生成回应
    responses = _generate_responses(meme_text, llm_fn)

    # 加载已学习的词库
    learned = _load_yaml(LEARNED_FILE)
    if "items" not in learned:
        learned = {
            "category": "已学习",
            "description": "从对话和网络自动学习的热梗",
            "items": []
        }

    # 检查是否已存在
    trigger_str = "|".join(trigger_words)
    for item in learned["items"]:
        if item.get("trigger") == trigger_str:
            # 更新回应
            item["responses"] = responses
            _save_yaml(LEARNED_FILE, learned)
            return True

    # 添加新条目
    learned["items"].append({
        "trigger": trigger_str,
        "responses": responses,
        "learned_at": datetime.now().strftime("%Y-%m-%d"),
        "source": "auto_learn"
    })

    _save_yaml(LEARNED_FILE, learned)
    return True


def learn_from_conversation(message: str, response: str) -> Optional[dict]:
    """
    从对话中学习新梗
    如果检测到可能是新梗，返回学习结果

    Args:
        message: 用户消息
        response: 助手回应

    Returns:
        学习结果或 None
    """
    # 简单的启发式检测
    meme_indicators = [
        "是什么意思", "什么意思", "啥意思",
        "梗", "热梗", "新梗", "流行语",
        "怎么说", "怎么回", "怎么接"
    ]

    is_meme_question = any(indicator in message for indicator in meme_indicators)

    if is_meme_question:
        # 提取可能的触发词
        # 简单实现：取用户消息中的关键词
        words = re.findall(r'[一-龥a-zA-Z]+', message)
        if words:
            return {
                "trigger_words": words[:3],  # 取前3个词作为触发词
                "context": message
            }

    return None


def auto_update_vocabulary(llm_fn=None):
    """
    自动更新词库
    1. 从网络获取热梗
    2. 为新梗生成回应
    3. 更新词库文件

    Args:
        llm_fn: LLM 生成函数
    """
    print("[MemeLearner] 开始自动更新词库...")

    # 获取热梗
    memes = _fetch_trending_memes()

    if not memes:
        print("[MemeLearner] 没有新的热梗需要学习")
        return

    # 学习每个梗
    learned_count = 0
    for meme in memes:
        trigger = meme.get("trigger", "")
        description = meme.get("description", "")

        if trigger:
            # 分割触发词
            trigger_words = [t.strip() for t in trigger.split("|") if t.strip()]

            if trigger_words:
                success = learn_meme(
                    meme_text=description or trigger,
                    trigger_words=trigger_words,
                    llm_fn=llm_fn
                )
                if success:
                    learned_count += 1

    print(f"[MemeLearner] 学习完成，新增 {learned_count} 个热梗")


def get_learned_memes() -> list[dict]:
    """获取已学习的热梗列表"""
    learned = _load_yaml(LEARNED_FILE)
    return learned.get("items", [])


def cleanup_old_memes(days: int = 30):
    """清理超过指定天数的旧梗"""
    learned = _load_yaml(LEARNED_FILE)
    if "items" not in learned:
        return

    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    original_count = len(learned["items"])
    learned["items"] = [
        item for item in learned["items"]
        if item.get("learned_at", "2000-01-01") > cutoff_str
    ]

    removed_count = original_count - len(learned["items"])
    if removed_count > 0:
        _save_yaml(LEARNED_FILE, learned)
        print(f"[MemeLearner] 清理了 {removed_count} 个过期热梗")


# ─── 定时任务接口 ───

def weekly_update(llm_fn=None):
    """
    每周更新任务
    可以被定时任务系统调用
    """
    print(f"[MemeLearner] 开始每周更新 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")

    # 1. 自动更新词库
    auto_update_vocabulary(llm_fn)

    # 2. 清理旧梗（保留最近60天）
    cleanup_old_memes(days=60)

    print("[MemeLearner] 每周更新完成")


if __name__ == "__main__":
    # 测试用
    print("热梗学习器测试")
    print("=" * 50)

    # 测试学习新梗
    test_memes = [
        {
            "trigger": "遥遥领先",
            "description": "华为发布会常用语，表示领先很多"
        },
        {
            "trigger": "泰裤辣",
            "description": "太酷了的谐音，表示很酷"
        }
    ]

    for meme in test_memes:
        trigger_words = [meme["trigger"]]
        success = learn_meme(meme["description"], trigger_words)
        print(f"学习 '{meme['trigger']}': {'成功' if success else '失败'}")

    # 显示已学习的梗
    learned = get_learned_memes()
    print(f"\n已学习 {len(learned)} 个热梗:")
    for item in learned[:5]:
        print(f"  - {item.get('trigger', '?')}: {item.get('responses', [])[:2]}")
