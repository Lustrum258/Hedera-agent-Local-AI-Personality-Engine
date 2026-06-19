"""
Hedera Monitor
运行时监控、追踪、回放 Agent 的决策过程
"""

import os
import json
import time
import threading
import uuid
from typing import Any, Callable, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict
from pathlib import Path


class EventType(Enum):
    MESSAGE_IN = "message_in"
    MESSAGE_OUT = "message_out"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PERSONA_SWITCH = "persona_switch"
    REFLECTION = "reflection"
    ERROR = "error"
    SAFETY_CHECK = "safety_check"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    CONTEXT_BUILD = "context_build"
    API_CALL = "api_call"
    NOISE_INJECT = "noise_inject"
    SLIDER_ADJUST = "slider_adjust"


@dataclass
class TraceEvent:
    """追踪事件"""
    id: str = ""
    trace_id: str = ""
    event_type: EventType = EventType.MESSAGE_IN
    timestamp: float = 0.0
    duration_ms: float = 0.0
    session_id: str = ""
    data: dict = field(default_factory=dict)
    parent_id: str = ""
    depth: int = 0
    tags: list = field(default_factory=list)


@dataclass
class TraceSession:
    """追踪会话"""
    trace_id: str = ""
    session_id: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    events: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class Monitor:
    """运行时监控器"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._traces: dict[str, TraceSession] = {}
        self._active_trace: Optional[TraceSession] = None
        self._lock = threading.Lock()
        self._callbacks: dict[str, list[Callable]] = defaultdict(list)
        self._metrics: dict[str, Any] = defaultdict(lambda: {"count": 0, "total_ms": 0})
        self._alert_rules: list[dict] = []
        self._log_dir = self.config.get("log_dir", "data/harness/traces")
        os.makedirs(self._log_dir, exist_ok=True)

    def start_trace(self, session_id: str, metadata: dict = None) -> str:
        """开始一个新的追踪"""
        trace_id = str(uuid.uuid4())[:12]
        trace = TraceSession(
            trace_id=trace_id,
            session_id=session_id,
            start_time=time.time(),
            metadata=metadata or {},
        )
        with self._lock:
            self._traces[trace_id] = trace
            self._active_trace = trace
        self._emit("on_trace_start", trace)
        return trace_id

    def end_trace(self, trace_id: str = None):
        """结束追踪"""
        with self._lock:
            trace = self._get_trace(trace_id)
            if trace:
                trace.end_time = time.time()
                self._emit("on_trace_end", trace)
                if self._active_trace and self._active_trace.trace_id == trace.trace_id:
                    self._active_trace = None

    def record_event(
        self,
        event_type: EventType,
        data: dict = None,
        trace_id: str = None,
        duration_ms: float = 0,
        parent_id: str = "",
        tags: list = None,
    ) -> str:
        """记录一个事件"""
        event = TraceEvent(
            id=str(uuid.uuid4())[:8],
            trace_id=trace_id or (self._active_trace.trace_id if self._active_trace else ""),
            event_type=event_type,
            timestamp=time.time(),
            duration_ms=duration_ms,
            session_id=self._active_trace.session_id if self._active_trace else "",
            data=data or {},
            parent_id=parent_id,
            tags=tags or [],
        )

        with self._lock:
            trace = self._get_trace(event.trace_id)
            if trace:
                event.depth = self._calc_depth(trace, parent_id)
                trace.events.append(event)

        self._update_metrics(event_type, duration_ms)
        self._check_alerts(event)
        self._emit("on_event", event)
        return event.id

    def _get_trace(self, trace_id: str = None) -> Optional[TraceSession]:
        if trace_id:
            return self._traces.get(trace_id)
        return self._active_trace

    def _calc_depth(self, trace: TraceSession, parent_id: str) -> int:
        if not parent_id:
            return 0
        for e in trace.events:
            if e.id == parent_id:
                return e.depth + 1
        return 0

    def _update_metrics(self, event_type: EventType, duration_ms: float):
        key = event_type.value
        self._metrics[key]["count"] += 1
        self._metrics[key]["total_ms"] += duration_ms

    def _check_alerts(self, event: TraceEvent):
        for rule in self._alert_rules:
            if self._match_alert(rule, event):
                self._emit("on_alert", rule, event)

    def _match_alert(self, rule: dict, event: TraceEvent) -> bool:
        if rule.get("event_type") and rule["event_type"] != event.event_type.value:
            return False
        if rule.get("max_duration_ms") and event.duration_ms > rule["max_duration_ms"]:
            return True
        if rule.get("pattern") and rule["pattern"] in str(event.data):
            return True
        return False

    def add_alert_rule(self, rule: dict):
        self._alert_rules.append(rule)

    def register_callback(self, event: str, callback: Callable):
        self._callbacks[event].append(callback)

    def _emit(self, event: str, *args, **kwargs):
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception:
                pass

    def get_trace(self, trace_id: str) -> Optional[dict]:
        """获取追踪数据"""
        trace = self._traces.get(trace_id)
        if not trace:
            return None
        return {
            "trace_id": trace.trace_id,
            "session_id": trace.session_id,
            "start_time": trace.start_time,
            "end_time": trace.end_time,
            "duration_ms": (trace.end_time - trace.start_time) * 1000 if trace.end_time else 0,
            "events": [asdict(e) for e in trace.events],
            "metadata": trace.metadata,
        }

    def get_active_traces(self) -> list:
        """获取活跃追踪"""
        return [
            {"trace_id": t.trace_id, "session_id": t.session_id, "event_count": len(t.events)}
            for t in self._traces.values()
            if not t.end_time
        ]

    def get_metrics(self) -> dict:
        """获取性能指标"""
        return {
            "event_counts": {k: v["count"] for k, v in self._metrics.items()},
            "total_duration_ms": {k: v["total_ms"] for k, v in self._metrics.items()},
            "avg_duration_ms": {
                k: v["total_ms"] / v["count"] if v["count"] > 0 else 0
                for k, v in self._metrics.items()
            },
            "active_traces": len([t for t in self._traces.values() if not t.end_time]),
            "total_traces": len(self._traces),
        }

    def export_trace(self, trace_id: str, path: str = None) -> str:
        """导出追踪数据"""
        trace_data = self.get_trace(trace_id)
        if not trace_data:
            return ""

        if not path:
            path = os.path.join(self._log_dir, f"trace_{trace_id}.json")

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, ensure_ascii=False, indent=2, default=str)
        return path

    def replay_trace(self, trace_id: str) -> list:
        """回放追踪事件"""
        trace_data = self.get_trace(trace_id)
        if not trace_data:
            return []

        events = sorted(trace_data["events"], key=lambda e: e["timestamp"])
        return events

    def analyze_trace(self, trace_id: str) -> dict:
        """分析追踪数据"""
        trace_data = self.get_trace(trace_id)
        if not trace_data:
            return {"error": "追踪不存在"}

        events = trace_data["events"]
        if not events:
            return {"error": "无事件数据"}

        event_types = defaultdict(int)
        tool_calls = []
        errors = []
        total_duration = 0

        for e in events:
            event_types[e["event_type"]] += 1
            if e["event_type"] == EventType.TOOL_CALL.value:
                tool_calls.append(e["data"].get("tool_name", "unknown"))
            if e["event_type"] == EventType.ERROR.value:
                errors.append(e["data"].get("message", ""))
            total_duration += e["duration_ms"]

        return {
            "trace_id": trace_id,
            "total_events": len(events),
            "event_type_distribution": dict(event_types),
            "tool_calls": tool_calls,
            "errors": errors,
            "total_duration_ms": total_duration,
            "avg_event_duration_ms": total_duration / len(events) if events else 0,
            "start_time": trace_data["start_time"],
            "end_time": trace_data["end_time"],
        }

    def clear_old_traces(self, max_age_hours: int = 24):
        """清理旧追踪"""
        cutoff = time.time() - max_age_hours * 3600
        with self._lock:
            to_remove = [
                tid for tid, t in self._traces.items()
                if t.end_time and t.end_time < cutoff
            ]
            for tid in to_remove:
                del self._traces[tid]

    def create_timer(self, name: str) -> Callable:
        """创建计时器上下文管理器"""
        class Timer:
            def __init__(self, monitor, name):
                self.monitor = monitor
                self.name = name
                self.start = 0

            def __enter__(self):
                self.start = time.time()
                return self

            def __exit__(self, *args):
                duration = (time.time() - self.start) * 1000
                self.monitor.record_event(
                    EventType.TOOL_CALL,
                    {"tool_name": self.name, "duration_ms": duration},
                    duration_ms=duration,
                )

        return Timer(self, name)
