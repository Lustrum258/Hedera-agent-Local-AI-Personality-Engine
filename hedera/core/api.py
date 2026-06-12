"""
Hedera API call wrapper
"""

import os
import json
import re
import threading
import time

_last_api_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
_usage_lock = threading.Lock()


def _call_api(messages: list, config: dict, temperature_override: float = None, tools: list = None, max_retries: int = 2, max_tokens_override: int = 0) -> dict:
    """
    调用 LLM API。
    - 工具列表 (`tools`) 一次性构建在 body 中，不存在遗漏
    - 自动重试（指数退避，最多 max_retries 次）
    - 指标记录
    """
    from hedera.core.logger import METRICS, Timer
    _timer = Timer()
    model_cfg = config.get("model", {})
    api_key = model_cfg.get("api_key", "") or os.environ.get(model_cfg.get("api_key_env", "HEDERA_API_KEY"), "")
    temp = temperature_override if temperature_override is not None else model_cfg.get("temperature", 0.7)
    endpoint = model_cfg.get("endpoint", "https://api.deepseek.com/chat/completions")
    model_name = model_cfg.get("name", "deepseek-chat")

    default_max = model_cfg.get("max_tokens", 4096)
    if max_tokens_override:
        effective_max = max_tokens_override
    else:
        effective_max = default_max

    # 一次性构建 body（tools 始终包含，空 list 传给 API 也没问题）
    body_payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temp,
        "max_tokens": effective_max,
    }
    if tools:
        body_payload["tools"] = tools
    last_exception = None
    for attempt in range(1, max_retries + 1):  # 重试 max_retries 次
        try:
            import requests as _requests
            resp = _requests.post(
                endpoint,
                json=body_payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=300,
            )
            data = resp.json()
            METRICS.record_api_call(success=True, latency=_timer.elapsed())
            # 捕获 API 返回的 token 用量
            if "usage" in data and isinstance(data["usage"], dict):
                with _usage_lock:
                    _last_api_usage.update(data["usage"])
            # 提取 API 错误信息
            if "error" in data:
                err = data["error"]
                if isinstance(err, dict):
                    err_msg = err.get("message", "") or err.get("msg", "") or str(err)
                else:
                    err_msg = str(err)
                raise ValueError(f"API 错误 ({resp.status_code}): {err_msg}")
            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0]["message"]
                # 防御：某些 API 返回 message 为字符串而非 dict
                if isinstance(msg, str):
                    msg = {"content": msg, "tool_calls": None}
                return msg
            else:
                raise ValueError(f"API 返回格式异常: {list(data.keys())}")
        except Exception as e:
            last_exception = e
            METRICS.record_api_call(success=False, latency=_timer.elapsed())
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
                _timer.reset()
                time.sleep(wait)

    return {"content": f"[Hedera API Error] {last_exception}", "tool_calls": None}


def _try_parse_xml_toolcall(content: str) -> list | None:
    results = []
    for m in re.finditer(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', content, re.DOTALL):
        name = m.group(1)
        body = m.group(2)
        params = {}
        for p in re.finditer(r'<parameter\s+name="([^"]+)"[^>]*>([^<]*)</parameter>', body):
            params[p.group(1)] = p.group(2)
        if name and params:
            results.append({
                "id": f"call_xml_{hash(content) % 10000}",
                "function": {"name": name, "arguments": json.dumps(params, ensure_ascii=False)},
            })
    return results if results else None


def get_last_api_usage():
    with _usage_lock:
        return dict(_last_api_usage)
