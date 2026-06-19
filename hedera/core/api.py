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


def _build_body(messages: list, config: dict, temperature_override: float = None, tools: list = None, max_tokens_override: int = 0, stream: bool = False) -> tuple:
    """构建请求 body 和 headers，供 _call_api / _call_api_stream 共用。"""
    model_cfg = config.get("model", {})
    api_key = model_cfg.get("api_key", "") or os.environ.get(model_cfg.get("api_key_env", "HEDERA_API_KEY"), "")
    temp = temperature_override if temperature_override is not None else model_cfg.get("temperature", 0.7)
    endpoint = model_cfg.get("endpoint", "https://api.deepseek.com/chat/completions")
    model_name = model_cfg.get("name", "deepseek-chat")
    default_max = model_cfg.get("max_tokens", 4096)
    effective_max = max_tokens_override if max_tokens_override else default_max

    body = {
        "model": model_name,
        "messages": messages,
        "temperature": temp,
        "max_tokens": effective_max,
        "stream": stream,
    }
    if tools:
        body["tools"] = tools
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return body, headers, endpoint


def _call_api(messages: list, config: dict, temperature_override: float = None, tools: list = None, max_retries: int = 2, max_tokens_override: int = 0) -> dict:
    """
    调用 LLM API（非流式）。
    - 自动重试（指数退避，最多 max_retries 次）
    - 指标记录
    """
    from hedera.core.logger import METRICS, Timer
    _timer = Timer()
    body_payload, headers, endpoint = _build_body(messages, config, temperature_override, tools, max_tokens_override, stream=False)
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            import requests as _requests
            resp = _requests.post(endpoint, json=body_payload, headers=headers, timeout=300)
            data = resp.json()
            METRICS.record_api_call(success=True, latency=_timer.elapsed())
            if "usage" in data and isinstance(data["usage"], dict):
                with _usage_lock:
                    _last_api_usage.update(data["usage"])
            if "error" in data:
                err = data["error"]
                if isinstance(err, dict):
                    err_msg = err.get("message", "") or err.get("msg", "") or str(err)
                else:
                    err_msg = str(err)
                raise ValueError(f"API 错误 ({resp.status_code}): {err_msg}")
            if "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0]["message"]
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


def _call_api_stream(messages: list, config: dict, temperature_override: float = None, tools: list = None, max_retries: int = 2, max_tokens_override: int = 0):
    """
    流式调用 LLM API（SSE）。
    生成器，逐块 yield：
      {"type": "token", "content": "..."}         — 文本 token
      {"type": "tool_calls", "tool_calls": [...]}  — 工具调用增量
      {"type": "usage", "usage": {...}}            — token 用量
      {"type": "done"}                             — 流结束
      {"type": "error", "error": "..."}            — 错误
    """
    from hedera.core.logger import METRICS, Timer
    _timer = Timer()
    body_payload, headers, endpoint = _build_body(messages, config, temperature_override, tools, max_tokens_override, stream=True)

    for attempt in range(1, max_retries + 1):
        try:
            import requests as _requests
            resp = _requests.post(endpoint, json=body_payload, headers=headers, timeout=300, stream=True)
            resp.raise_for_status()
            resp.encoding = "utf-8"

            collected_content = ""
            collected_tool_calls = {}  # index -> {id, type, function: {name, arguments}}

            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                line = line.strip()
                if line == "data: [DONE]":
                    break
                if not line.startswith("data: "):
                    continue
                json_str = line[6:]
                try:
                    chunk = json.loads(json_str)
                except json.JSONDecodeError:
                    continue

                # usage 信息（部分 API 在最后一个 chunk 返回）
                if "usage" in chunk and isinstance(chunk["usage"], dict):
                    with _usage_lock:
                        _last_api_usage.update(chunk["usage"])
                    yield {"type": "usage", "usage": chunk["usage"]}

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})

                # 文本 token
                if "content" in delta and delta["content"]:
                    collected_content += delta["content"]
                    yield {"type": "token", "content": delta["content"]}

                # 工具调用增量
                if "tool_calls" in delta and delta["tool_calls"]:
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {
                                "id": tc.get("id", f"call_{idx}"),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.get("id"):
                            collected_tool_calls[idx]["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            collected_tool_calls[idx]["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            collected_tool_calls[idx]["function"]["arguments"] += fn["arguments"]

            METRICS.record_api_call(success=True, latency=_timer.elapsed())

            # 组装最终结果
            result = {"content": collected_content, "tool_calls": None}
            if collected_tool_calls:
                tc_list = [collected_tool_calls[i] for i in sorted(collected_tool_calls.keys())]
                result["tool_calls"] = tc_list
            yield {"type": "done", "result": result}
            return

        except Exception as e:
            last_exception = e
            METRICS.record_api_call(success=False, latency=_timer.elapsed())
            if attempt < max_retries:
                wait = min(2 ** attempt, 30)
                _timer.reset()
                time.sleep(wait)

    yield {"type": "error", "error": str(last_exception)}


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
