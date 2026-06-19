"""
Hedera Enhanced Sandbox
增强的安全沙箱约束机制
"""

import os
import sys
import json
import re
import ast
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PolicyLevel(Enum):
    STRICT = "strict"      # 最严格：禁止所有外部访问
    MODERATE = "moderate"  # 中等：允许受控的外部访问
    PERMISSIVE = "permissive"  # 宽松：仅阻止明显危险操作


@dataclass
class SandboxPolicy:
    """沙箱策略"""
    level: PolicyLevel = PolicyLevel.MODERATE
    allow_network: bool = False
    allow_file_write: bool = True
    allow_subprocess: bool = False
    allow_imports: list = field(default_factory=lambda: ["math", "json", "re", "datetime", "collections", "itertools"])
    blocked_imports: list = field(default_factory=lambda: ["os", "sys", "subprocess", "shutil", "ctypes", "socket"])
    max_memory_mb: int = 256
    max_cpu_seconds: int = 30
    max_output_chars: int = 50000
    allowed_paths: list = field(default_factory=list)
    blocked_paths: list = field(default_factory=lambda: [
        "C:\\Windows", "C:\\Program Files", "/etc", "/usr", "/root",
        "~/.ssh", "~/.aws", "~/.gnupg",
    ])
    env_whitelist: list = field(default_factory=lambda: ["PATH", "HOME", "TEMP", "TMP", "PYTHONPATH"])


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool = False
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    duration_ms: float = 0
    violations: list = field(default_factory=list)
    resource_usage: dict = field(default_factory=dict)
    sandboxed: bool = True


class EnhancedSandbox:
    """增强沙箱执行器"""

    def __init__(self, policy: SandboxPolicy = None):
        self.policy = policy or SandboxPolicy()
        self._temp_dir = None
        self._lock = threading.Lock()
        self._execution_log: list[dict] = []
        self._setup_temp_dir()

    def _setup_temp_dir(self):
        self._temp_dir = tempfile.mkdtemp(prefix="hedera_sandbox_")

    def execute_python(self, code: str, timeout: int = None) -> SandboxResult:
        """在沙箱中执行 Python 代码"""
        timeout = timeout or self.policy.max_cpu_seconds
        start_time = time.time()

        violations = self._check_code_safety(code)
        if violations:
            return SandboxResult(
                success=False,
                stderr=f"安全检查失败:\n" + "\n".join(f"  - {v}" for v in violations),
                violations=violations,
            )

        wrapped_code = self._wrap_code(code)
        script_path = os.path.join(self._temp_dir, f"script_{os.getpid()}.py")

        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(wrapped_code)

            env = self._prepare_environment()
            cmd = [sys.executable or "python", "-u", script_path]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=self._temp_dir,
                encoding="utf-8",
                errors="replace",
            )

            duration = (time.time() - start_time) * 1000
            output = self._truncate(result.stdout)

            self._log_execution(code, result.returncode == 0, duration)

            return SandboxResult(
                success=result.returncode == 0,
                stdout=output,
                stderr=self._truncate(result.stderr),
                returncode=result.returncode,
                duration_ms=duration,
                resource_usage={"cpu_time": duration / 1000},
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                stderr=f"执行超时 ({timeout}s)",
                violations=["timeout"],
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                stderr=f"执行错误: {str(e)}",
            )
        finally:
            try:
                if os.path.exists(script_path):
                    os.unlink(script_path)
            except Exception:
                pass

    def execute_shell(self, cmd: str, timeout: int = None) -> SandboxResult:
        """在沙箱中执行 Shell 命令"""
        timeout = timeout or self.policy.max_cpu_seconds
        start_time = time.time()

        violations = self._check_shell_safety(cmd)
        if violations:
            return SandboxResult(
                success=False,
                stderr=f"安全检查失败:\n" + "\n".join(f"  - {v}" for v in violations),
                violations=violations,
            )

        try:
            env = self._prepare_environment()
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=self._temp_dir,
                encoding="utf-8",
                errors="replace",
            )

            duration = (time.time() - start_time) * 1000

            return SandboxResult(
                success=result.returncode == 0,
                stdout=self._truncate(result.stdout),
                stderr=self._truncate(result.stderr),
                returncode=result.returncode,
                duration_ms=duration,
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                stderr=f"执行超时 ({timeout}s)",
                violations=["timeout"],
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                stderr=f"执行错误: {str(e)}",
            )

    def _check_code_safety(self, code: str) -> list:
        """检查代码安全性"""
        violations = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return [f"语法错误: {e}"]

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if module in self.policy.blocked_imports:
                        violations.append(f"禁止导入模块: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split('.')[0]
                    if module in self.policy.blocked_imports:
                        violations.append(f"禁止从 {node.module} 导入")

            elif isinstance(node, ast.Call):
                func_name = self._get_func_name(node)
                if func_name in ["eval", "exec", "compile", "os.system", "subprocess.call"]:
                    violations.append(f"禁止调用函数: {func_name}")

        code_lower = code.lower()
        dangerous_patterns = [
            ("__subclasses__", "禁止访问 __subclasses__"),
            ("__globals__", "禁止访问 __globals__"),
            ("__builtins__", "禁止访问 __builtins__"),
            ("import os", "禁止导入 os 模块"),
            ("import subprocess", "禁止导入 subprocess 模块"),
            ("import sys", "禁止导入 sys 模块"),
        ]
        for pattern, msg in dangerous_patterns:
            if pattern in code_lower:
                if msg not in violations:
                    violations.append(msg)

        return violations

    def _check_shell_safety(self, cmd: str) -> list:
        """检查 Shell 命令安全性"""
        violations = []
        cmd_lower = cmd.lower().strip()

        dangerous_commands = [
            "rm -rf", "rmdir /s", "del /f",
            "shutdown", "reboot", "format",
            "sudo", "su ", "chmod 777",
            "mkfs", "dd if=",
            "curl", "wget", "nc ", "netcat",
        ]
        for dangerous in dangerous_commands:
            if dangerous in cmd_lower:
                violations.append(f"禁止危险命令: {dangerous}")

        if ">" in cmd and ("null" in cmd_lower or "nul" in cmd_lower):
            violations.append("禁止重定向到空设备")

        return violations

    def _get_func_name(self, node: ast.Call) -> str:
        """获取函数调用名称"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            parts = []
            current = node.func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        return "unknown"

    def _wrap_code(self, code: str) -> str:
        """包装代码，添加安全限制"""
        blocked_imports_str = ", ".join(f"'{m}'" for m in self.policy.blocked_imports)
        return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hedera Enhanced Sandbox"""

import sys

_BLOCKED_MODULES = {{{blocked_imports_str}}}

class ImportBlocker:
    def find_module(self, name, path=None):
        if name.split('.')[0] in _BLOCKED_MODULES:
            return self
        return None

    def load_module(self, name):
        raise ImportError(f"沙箱禁止导入模块: {{name}}")

sys.meta_path.insert(0, ImportBlocker())

# 资源限制
import signal
def _timeout_handler(signum, frame):
    raise TimeoutError("执行超时")
if hasattr(signal, 'SIGALRM'):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm({self.policy.max_cpu_seconds})

try:
{self._indent_code(code, 4)}
except TimeoutError:
    print("执行超时", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"错误: {{type(e).__name__}}: {{e}}", file=sys.stderr)
    sys.exit(1)
finally:
    if hasattr(signal, 'SIGALRM'):
        signal.alarm(0)
'''

    def _indent_code(self, code: str, spaces: int) -> str:
        indent = " " * spaces
        lines = code.split("\n")
        return "\n".join(indent + line if line.strip() else "" for line in lines)

    def _prepare_environment(self) -> dict:
        env = {}
        for key in self.policy.env_whitelist:
            value = os.environ.get(key)
            if value:
                env[key] = value
        env["PYTHONPATH"] = self._temp_dir
        env["HOME"] = self._temp_dir
        env["TEMP"] = self._temp_dir
        env["TMP"] = self._temp_dir
        return env

    def _truncate(self, text: str) -> str:
        if len(text) > self.policy.max_output_chars:
            return text[:self.policy.max_output_chars] + f"\n...（已截断，仅显示前 {self.policy.max_output_chars} 字符）"
        return text

    def _log_execution(self, code: str, success: bool, duration_ms: float):
        self._execution_log.append({
            "timestamp": time.time(),
            "code_hash": hash(code) % 10000,
            "success": success,
            "duration_ms": duration_ms,
        })

    def get_execution_log(self) -> list:
        return self._execution_log.copy()

    def cleanup(self):
        import shutil
        if self._temp_dir and os.path.exists(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    def __del__(self):
        self._cleanup_script()

    def _cleanup_script(self):
        pass


class SandboxManager:
    """沙箱管理器"""

    def __init__(self):
        self._sandboxes: dict[str, EnhancedSandbox] = {}
        self._policies: dict[str, SandboxPolicy] = {}
        self._lock = threading.Lock()

    def create_sandbox(self, name: str, policy: SandboxPolicy = None) -> EnhancedSandbox:
        with self._lock:
            sandbox = EnhancedSandbox(policy)
            self._sandboxes[name] = sandbox
            if policy:
                self._policies[name] = policy
            return sandbox

    def get_sandbox(self, name: str) -> Optional[EnhancedSandbox]:
        return self._sandboxes.get(name)

    def remove_sandbox(self, name: str):
        with self._lock:
            sandbox = self._sandboxes.pop(name, None)
            if sandbox:
                sandbox.cleanup()
            self._policies.pop(name, None)

    def list_sandboxes(self) -> list:
        return [
            {"name": name, "policy_level": self._policies.get(name, SandboxPolicy()).level.value}
            for name in self._sandboxes
        ]

    def cleanup_all(self):
        with self._lock:
            for sandbox in self._sandboxes.values():
                sandbox.cleanup()
            self._sandboxes.clear()
            self._policies.clear()
