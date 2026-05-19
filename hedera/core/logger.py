"""
Hedera 结构化日志 & 指标系统
替换所有 print()，提供日志级别、请求追踪、运行时指标。
"""

import time
import json
import os
import sys
import traceback
import threading
from collections import defaultdict
from datetime import datetime, timezone

# ─── 全局指标收集器 ───────────

class _Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests = 0
        self._tool_calls = defaultdict(int)         # tool_name → count
        self._tool_errors = defaultdict(int)         # tool_name → error_count
        self._tool_latency = defaultdict(list)       # tool_name → [latency_seconds]
        self._api_calls = 0
        self._api_errors = 0
        self._api_latencies = []                     # [latency_seconds]
        self._start_time = time.time()
        self._recent_errors = []                     # ring buffer, last 20

    def record_request(self):
        with self._lock:
            self._requests += 1

    def record_tool_call(self, name: str, success: bool, latency: float):
        with self._lock:
            self._tool_calls[name] += 1
            if not success:
                self._tool_errors[name] += 1
            self._tool_latency[name].append(latency)
            # 限制记录条数防内存膨胀
            if len(self._tool_latency[name]) > 100:
                self._tool_latency[name] = self._tool_latency[name][-50:]

    def record_api_call(self, success: bool, latency: float):
        with self._lock:
            self._api_calls += 1
            if not success:
                self._api_errors += 1
            self._api_latencies.append(latency)
            if len(self._api_latencies) > 100:
                self._api_latencies = self._api_latencies[-50:]

    def record_error(self, source: str, message: str):
        with self._lock:
            self._recent_errors.append({
                "time": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "message": message[:200],
            })
            if len(self._recent_errors) > 20:
                self._recent_errors = self._recent_errors[-20:]

    def snapshot(self) -> dict:
        with self._lock:
            uptime = time.time() - self._start_time
            def _avg(lst):
                return round(sum(lst) / len(lst), 3) if lst else 0.0

            tool_stats = {}
            for name in self._tool_calls:
                latencies = self._tool_latency.get(name, [])
                tool_stats[name] = {
                    "calls": self._tool_calls[name],
                    "errors": self._tool_errors.get(name, 0),
                    "avg_latency": _avg(latencies),
                }

            return {
                "uptime_seconds": round(uptime, 1),
                "requests": self._requests,
                "api_calls": self._api_calls,
                "api_errors": self._api_errors,
                "api_avg_latency": _avg(self._api_latencies),
                "tools": tool_stats,
                "recent_errors": list(self._recent_errors),
            }


METRICS = _Metrics()


# ─── 结构化日志 ───────────

_LOG_LEVELS = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3, "FATAL": 4}
_LOG_LEVEL = "INFO"  # 可通过环境变量 HEDERA_LOG_LEVEL 覆盖


def _get_log_level() -> int:
    return _LOG_LEVELS.get(os.environ.get("HEDERA_LOG_LEVEL", _LOG_LEVEL), 1)


def _log(level: str, message: str, **extra):
    """结构化日志输出：JSON 一行一条，包含时间戳、级别、源码位置"""
    if _LOG_LEVELS.get(level, 1) < _get_log_level():
        return

    # 获取调用栈
    frame = sys._getframe(2)
    mod = frame.f_globals.get("__name__", "?")
    lineno = frame.f_lineno

    entry = {
        "t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "lvl": level,
        "src": f"{mod}:{lineno}",
        "msg": message,
    }
    if extra:
        entry.update(extra)

    # 输出到 stderr（不和 HTTP 响应流混在一起）
    line = json.dumps(entry, ensure_ascii=False)
    print(line, file=sys.stderr, flush=True)


def debug(msg: str, **kw):   _log("DEBUG", msg, **kw)
def info(msg: str, **kw):    _log("INFO", msg, **kw)
def warn(msg: str, **kw):    _log("WARN", msg, **kw)

def error(msg: str, exc: BaseException | None = None, **kw):
    if exc:
        kw["exc"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    _log("ERROR", msg, **kw)
    METRICS.record_error(kw.get("source", "?"), msg)

def fatal(msg: str, exc: BaseException | None = None, **kw):
    if exc:
        kw["exc"] = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    _log("FATAL", msg, **kw)
    METRICS.record_error(kw.get("source", "?"), msg)


# ─── 请求追踪 ───────────

_request_id_counter = 0
_request_id_lock = threading.Lock()

def new_request_id() -> str:
    """生成请求追踪 ID"""
    global _request_id_counter
    with _request_id_lock:
        _request_id_counter += 1
        return f"r{_request_id_counter:06d}"


class Timer:
    """简易性能计时器"""
    def __init__(self):
        self.reset()

    def reset(self):
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def __enter__(self):
        self.reset()
        return self

    def __exit__(self, *args):
        pass
