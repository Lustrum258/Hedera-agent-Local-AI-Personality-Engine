"""
Hedera Test Harness Runner
自动化测试 Agent 行为、工具调用、人格一致性
"""

import os
import json
import time
import hashlib
import threading
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from hedera.core.router import process_message
from hedera.core.tools import call_tool, ALL_TOOL_NAMES
from hedera.core.memory import build_system_prompt


class TestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class TestAssertion:
    """测试断言"""
    type: str  # contains, equals, matches, tool_call, persona, latency, token_count
    expected: Any
    actual: Any = None
    passed: bool = False
    message: str = ""


@dataclass
class TestCase:
    """测试用例"""
    id: str
    name: str
    description: str = ""
    category: str = "general"  # general, tool, persona, safety, performance
    input_message: str = ""
    expected_output: str = ""
    expected_tools: list = field(default_factory=list)
    expected_persona_traits: list = field(default_factory=list)
    forbidden_patterns: list = field(default_factory=list)
    max_latency_ms: float = 0
    max_tokens: int = 0
    timeout_seconds: int = 60
    session_config: dict = field(default_factory=dict)
    assertions: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    priority: int = 1  # 1=high, 2=medium, 3=low


@dataclass
class TestResult:
    """测试结果"""
    test_id: str
    test_name: str
    status: TestStatus = TestStatus.PENDING
    assertions: list = field(default_factory=list)
    actual_output: str = ""
    actual_tools: list = field(default_factory=list)
    latency_ms: float = 0
    tokens_used: int = 0
    error_message: str = ""
    timestamp: float = 0
    trace_id: str = ""


class HarnessRunner:
    """测试运行器"""

    def __init__(self, config: dict, workspace_dir: str = None):
        self.config = config
        self.workspace_dir = workspace_dir or os.getcwd()
        self.results: list[TestResult] = []
        self._lock = threading.Lock()
        self._running = False
        self._callbacks: dict[str, list[Callable]] = {
            "on_test_start": [],
            "on_test_end": [],
            "on_suite_start": [],
            "on_suite_end": [],
        }

    def register_callback(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event: str, *args, **kwargs):
        for cb in self._callbacks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception:
                pass

    def load_tests(self, path: str) -> list[TestCase]:
        """从 JSON/YAML 文件加载测试用例"""
        if not os.path.exists(path):
            return []
        
        with open(path, "r", encoding="utf-8") as f:
            if path.endswith(".json"):
                data = json.load(f)
            elif path.endswith((".yaml", ".yml")):
                import yaml
                data = yaml.safe_load(f)
            else:
                return []

        tests = []
        for item in data.get("tests", []):
            tc = TestCase(
                id=item.get("id", hashlib.md5(item.get("name", "").encode()).hexdigest()[:8]),
                name=item.get("name", ""),
                description=item.get("description", ""),
                category=item.get("category", "general"),
                input_message=item.get("input_message", ""),
                expected_output=item.get("expected_output", ""),
                expected_tools=item.get("expected_tools", []),
                expected_persona_traits=item.get("expected_persona_traits", []),
                forbidden_patterns=item.get("forbidden_patterns", []),
                max_latency_ms=item.get("max_latency_ms", 0),
                max_tokens=item.get("max_tokens", 0),
                timeout_seconds=item.get("timeout_seconds", 60),
                session_config=item.get("session_config", {}),
                tags=item.get("tags", []),
                priority=item.get("priority", 2),
            )
            tests.append(tc)
        return tests

    def run_test(self, test: TestCase) -> TestResult:
        """运行单个测试用例"""
        result = TestResult(
            test_id=test.id,
            test_name=test.name,
            timestamp=time.time(),
            trace_id=hashlib.md5(f"{test.id}_{time.time()}".encode()).hexdigest()[:12],
        )

        self._emit("on_test_start", test, result)

        try:
            result.status = TestStatus.RUNNING
            start_time = time.time()

            session_id = test.session_config.get("session_id", f"_test_{test.id}")
            session_config = {**self.config, **test.session_config}

            output, tools_used = process_message(
                test.input_message,
                session_config,
                session_id=session_id,
            )

            result.latency_ms = (time.time() - start_time) * 1000
            result.actual_output = output or ""
            result.actual_tools = tools_used if tools_used else []

            self._run_assertions(test, result)

            passed = all(a.passed for a in result.assertions) if result.assertions else True
            result.status = TestStatus.PASSED if passed else TestStatus.FAILED

        except TimeoutError:
            result.status = TestStatus.ERROR
            result.error_message = f"测试超时 ({test.timeout_seconds}s)"
        except Exception as e:
            result.status = TestStatus.ERROR
            result.error_message = str(e)

        self._emit("on_test_end", test, result)

        with self._lock:
            self.results.append(result)

        return result

    def run_suite(self, tests: list[TestCase], parallel: bool = False, max_workers: int = 4) -> list[TestResult]:
        """运行测试套件"""
        self._emit("on_suite_start", tests)
        self._running = True
        results = []

        if parallel and len(tests) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.run_test, t): t for t in tests}
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as e:
                        tc = futures[future]
                        results.append(TestResult(
                            test_id=tc.id,
                            test_name=tc.name,
                            status=TestStatus.ERROR,
                            error_message=str(e),
                        ))
        else:
            for test in tests:
                if not self._running:
                    break
                results.append(self.run_test(test))

        self._running = False
        self._emit("on_suite_end", results)
        return results

    def stop(self):
        self._running = False

    def _run_assertions(self, test: TestCase, result: TestResult):
        """执行所有断言检查"""
        assertions = []

        if test.expected_output:
            a = self._assert_contains(result.actual_output, test.expected_output)
            assertions.append(a)

        if test.expected_tools:
            a = self._assert_tool_calls(result.actual_tools, test.expected_tools)
            assertions.append(a)

        if test.forbidden_patterns:
            a = self._assert_no_forbidden(result.actual_output, test.forbidden_patterns)
            assertions.append(a)

        if test.max_latency_ms > 0:
            a = self._assert_latency(result.latency_ms, test.max_latency_ms)
            assertions.append(a)

        if test.max_tokens > 0:
            a = self._assert_token_count(result.tokens_used, test.max_tokens)
            assertions.append(a)

        if test.expected_persona_traits:
            a = self._assert_persona(result.actual_output, test.expected_persona_traits)
            assertions.append(a)

        result.assertions = assertions

    def _assert_contains(self, actual: str, expected: str) -> TestAssertion:
        a = TestAssertion(type="contains", expected=expected, actual=actual)
        a.passed = expected.lower() in actual.lower()
        a.message = "输出包含预期内容" if a.passed else f"输出不包含: {expected[:50]}"
        return a

    def _assert_tool_calls(self, actual: list, expected: list) -> TestAssertion:
        a = TestAssertion(type="tool_call", expected=expected, actual=actual)
        actual_set = set(actual)
        expected_set = set(expected)
        a.passed = expected_set.issubset(actual_set)
        missing = expected_set - actual_set
        a.message = "工具调用匹配" if a.passed else f"缺少工具调用: {missing}"
        return a

    def _assert_no_forbidden(self, actual: str, patterns: list) -> TestAssertion:
        a = TestAssertion(type="forbidden", expected=patterns, actual=actual)
        found = [p for p in patterns if p.lower() in actual.lower()]
        a.passed = len(found) == 0
        a.message = "无禁止内容" if a.passed else f"包含禁止内容: {found}"
        return a

    def _assert_latency(self, actual_ms: float, max_ms: float) -> TestAssertion:
        a = TestAssertion(type="latency", expected=max_ms, actual=actual_ms)
        a.passed = actual_ms <= max_ms
        a.message = f"延迟 {actual_ms:.0f}ms <= {max_ms:.0f}ms" if a.passed else f"延迟超限: {actual_ms:.0f}ms > {max_ms:.0f}ms"
        return a

    def _assert_token_count(self, actual: int, max_tokens: int) -> TestAssertion:
        a = TestAssertion(type="token_count", expected=max_tokens, actual=actual)
        a.passed = actual <= max_tokens
        a.message = "Token 数量在限制内" if a.passed else f"Token 超限: {actual} > {max_tokens}"
        return a

    def _assert_persona(self, actual: str, traits: list) -> TestAssertion:
        a = TestAssertion(type="persona", expected=traits, actual=actual)
        trait_indicators = {
            "直接": ["直接", "简单", "干脆"],
            "温和": ["温柔", "轻声", "慢慢"],
            "有态度": ["我觉得", "我认为", "我的看法"],
            "独立": ["我自己", "我的判断", "我选择"],
        }
        matched = []
        for trait in traits:
            indicators = trait_indicators.get(trait, [trait])
            if any(ind in actual for ind in indicators):
                matched.append(trait)
        a.passed = len(matched) >= len(traits) * 0.5
        a.message = f"人格特征匹配: {matched}" if a.passed else f"人格特征不匹配: 期望 {traits}, 匹配 {matched}"
        return a

    def get_summary(self) -> dict:
        """获取测试结果摘要"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        errors = sum(1 for r in self.results if r.status == TestStatus.ERROR)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "pass_rate": passed / total if total > 0 else 0,
            "avg_latency_ms": sum(r.latency_ms for r in self.results) / total if total > 0 else 0,
        }

    def export_results(self, path: str, format: str = "json"):
        """导出测试结果"""
        data = {
            "summary": self.get_summary(),
            "results": [
                {
                    "test_id": r.test_id,
                    "test_name": r.test_name,
                    "status": r.status.value,
                    "latency_ms": r.latency_ms,
                    "assertions": [
                        {"type": a.type, "passed": a.passed, "message": a.message}
                        for a in r.assertions
                    ],
                    "error": r.error_message,
                    "timestamp": r.timestamp,
                    "trace_id": r.trace_id,
                }
                for r in self.results
            ],
        }

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            if format == "json":
                json.dump(data, f, ensure_ascii=False, indent=2)
            elif format == "yaml":
                import yaml
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
