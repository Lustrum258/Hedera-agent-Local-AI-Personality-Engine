"""
Hedera 沙箱隔离模块
提供安全的代码执行环境，隔离危险操作
"""

import os
import sys
import subprocess
import tempfile
import threading
import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from hedera.core.constants import (
    PYTHON_TIMEOUT, MAX_TIMEOUT, SHELL_TIMEOUT,
    MAX_OUTPUT_LENGTH, BLOCKED_PATHS_WRITE,
)


class SandboxError(Exception):
    """沙箱执行异常"""
    pass


class SandboxConfig:
    """沙箱配置"""
    
    def __init__(self):
        # 资源限制
        self.max_memory_mb = 256  # 最大内存（MB）
        self.max_cpu_time = 30  # 最大CPU时间（秒）
        self.max_processes = 10  # 最大进程数
        
        # 网络限制
        self.allow_network = False  # 是否允许网络访问
        self.allowed_hosts = []  # 允许访问的主机
        
        # 文件系统限制
        self.readonly_paths = []  # 只读路径
        self.writable_paths = []  # 可写路径
        self.temp_dir = None  # 临时目录
        
        # 环境变量
        self.env_vars = {}  # 额外环境变量
        self.remove_env_vars = []  # 需要移除的环境变量


class PythonSandbox:
    """Python 代码沙箱执行器"""
    
    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
        self._setup_temp_dir()
    
    def _setup_temp_dir(self):
        """设置临时目录"""
        if self.config.temp_dir is None:
            self.config.temp_dir = tempfile.mkdtemp(prefix="hedera_sandbox_")
        os.makedirs(self.config.temp_dir, exist_ok=True)
    
    def execute(self, code: str, timeout: int = PYTHON_TIMEOUT) -> Dict[str, Any]:
        """
        在沙箱中执行 Python 代码
        
        Args:
            code: Python 代码
            timeout: 超时时间（秒）
            
        Returns:
            执行结果字典
        """
        # 限制超时范围
        timeout = min(max(timeout, 1), MAX_TIMEOUT)
        
        # 准备执行环境
        env = self._prepare_environment()
        
        # 创建临时脚本
        script_path = self._create_script(code)
        
        try:
            # 构建执行命令
            cmd = self._build_command(script_path)
            
            # 执行代码
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=self.config.temp_dir,
                encoding="utf-8",
                errors="replace",
            )
            
            return {
                "stdout": self._truncate_output(result.stdout),
                "stderr": self._truncate_output(result.stderr),
                "returncode": result.returncode,
                "success": result.returncode == 0,
                "sandbox": True,
            }
            
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"沙箱执行超时（{timeout}s）",
                "returncode": -1,
                "success": False,
                "sandbox": True,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"沙箱执行错误: {str(e)}",
                "returncode": -1,
                "success": False,
                "sandbox": True,
            }
        finally:
            # 清理临时脚本
            self._cleanup_script(script_path)
    
    def _prepare_environment(self) -> Dict[str, str]:
        """准备执行环境变量"""
        # 基础环境变量
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": self.config.temp_dir,
            "HOME": self.config.temp_dir,
            "TEMP": self.config.temp_dir,
            "TMP": self.config.temp_dir,
        }
        
        # 添加允许的环境变量
        for key, value in self.config.env_vars.items():
            env[key] = value
        
        # 移除敏感环境变量
        sensitive_vars = [
            "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID",
            "AZURE_CLIENT_SECRET", "AZURE_CLIENT_ID",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "DATABASE_URL", "REDIS_URL",
            "SECRET_KEY", "JWT_SECRET",
        ]
        
        for var in sensitive_vars + self.config.remove_env_vars:
            env.pop(var, None)
        
        return env
    
    def _create_script(self, code: str) -> str:
        """创建临时脚本文件"""
        script_path = os.path.join(self.config.temp_dir, f"script_{os.getpid()}.py")
        
        # 添加安全包装器
        wrapper_code = self._wrap_code(code)
        
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(wrapper_code)
        
        return script_path
    
    def _wrap_code(self, code: str) -> str:
        """包装代码，添加安全限制"""
        return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hedera 沙箱执行脚本"""

import sys
import os

# 禁止危险操作
_BLOCKED_MODULES = {{'ctypes', 'signal', 'mmap', 'socket', 'http', 'urllib', 'requests', 'subprocess', 'shutil'}}

class ImportBlocker:
    def find_module(self, name, path=None):
        if name.split('.')[0] in _BLOCKED_MODULES:
            return self
        return None
    
    def load_module(self, name):
        raise ImportError(f"沙箱禁止导入模块: {{name}}")

sys.meta_path.insert(0, ImportBlocker())

# 用户代码开始
try:
{self._indent_code(code, 4)}
except Exception as e:
    print(f"错误: {{type(e).__name__}}: {{e}}", file=sys.stderr)
    sys.exit(1)
'''
    
    def _indent_code(self, code: str, spaces: int) -> str:
        """缩进代码"""
        indent = " " * spaces
        lines = code.split("\n")
        return "\n".join(indent + line if line.strip() else "" for line in lines)
    
    def _build_command(self, script_path: str) -> list:
        """构建执行命令"""
        python_exe = sys.executable or "python"
        
        # 基础命令
        cmd = [python_exe, "-u", script_path]
        
        # 添加安全参数
        if sys.platform != "win32":
            # Linux/macOS: 使用 ulimit
            cmd = ["timeout", str(self.config.max_cpu_time)] + cmd
        
        return cmd
    
    def _cleanup_script(self, script_path: str):
        """清理临时脚本"""
        try:
            if os.path.exists(script_path):
                os.unlink(script_path)
        except Exception:
            pass
    
    def _truncate_output(self, text: str) -> str:
        """截断输出"""
        if len(text) > MAX_OUTPUT_LENGTH:
            return text[:MAX_OUTPUT_LENGTH] + f"\n...（已截断，仅显示前 {MAX_OUTPUT_LENGTH} 字符）"
        return text


class ShellSandbox:
    """Shell 命令沙箱执行器"""
    
    def __init__(self, config: Optional[SandboxConfig] = None):
        self.config = config or SandboxConfig()
    
    def execute(self, cmd: str, timeout: int = SHELL_TIMEOUT) -> Dict[str, Any]:
        """
        在沙箱中执行 Shell 命令
        
        Args:
            cmd: Shell 命令
            timeout: 超时时间（秒）
            
        Returns:
            执行结果字典
        """
        # 限制超时范围
        timeout = min(max(timeout, 1), MAX_TIMEOUT)
        
        # 准备执行环境
        env = self._prepare_environment()
        
        # 检查命令安全性
        if not self._check_command_safety(cmd):
            return {
                "stdout": "",
                "stderr": "命令被沙箱安全策略阻止",
                "returncode": -1,
                "success": False,
                "sandbox": True,
            }
        
        try:
            # 执行命令
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=self.config.temp_dir or tempfile.gettempdir(),
                encoding="utf-8",
                errors="replace",
            )
            
            return {
                "stdout": self._truncate_output(result.stdout),
                "stderr": self._truncate_output(result.stderr),
                "returncode": result.returncode,
                "success": result.returncode == 0,
                "sandbox": True,
            }
            
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": f"沙箱执行超时（{timeout}s）",
                "returncode": -1,
                "success": False,
                "sandbox": True,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"沙箱执行错误: {str(e)}",
                "returncode": -1,
                "success": False,
                "sandbox": True,
            }
    
    def _prepare_environment(self) -> Dict[str, str]:
        """准备执行环境变量"""
        env = os.environ.copy()
        
        # 移除敏感环境变量
        sensitive_vars = [
            "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID",
            "AZURE_CLIENT_SECRET", "AZURE_CLIENT_ID",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "DATABASE_URL", "REDIS_URL",
            "SECRET_KEY", "JWT_SECRET",
        ]
        
        for var in sensitive_vars + self.config.remove_env_vars:
            env.pop(var, None)
        
        # 添加配置的环境变量
        for key, value in self.config.env_vars.items():
            env[key] = value
        
        return env
    
    def _check_command_safety(self, cmd: str) -> bool:
        """检查命令安全性"""
        cmd_lower = cmd.lower().strip()
        
        # 危险命令列表
        dangerous_commands = [
            "rm -rf", "rmdir /s", "del /f",
            "shutdown", "reboot", "format",
            "sudo", "su ", "chmod 777",
            "curl", "wget",  # 限制网络访问
        ]
        
        for dangerous in dangerous_commands:
            if dangerous in cmd_lower:
                return False
        
        return True
    
    def _truncate_output(self, text: str) -> str:
        """截断输出"""
        if len(text) > MAX_OUTPUT_LENGTH:
            return text[:MAX_OUTPUT_LENGTH] + f"\n...（已截断，仅显示前 {MAX_OUTPUT_LENGTH} 字符）"
        return text


# 全局沙箱实例
_python_sandbox: Optional[PythonSandbox] = None
_shell_sandbox: Optional[ShellSandbox] = None


def get_python_sandbox() -> PythonSandbox:
    """获取 Python 沙箱实例"""
    global _python_sandbox
    if _python_sandbox is None:
        _python_sandbox = PythonSandbox()
    return _python_sandbox


def get_shell_sandbox() -> ShellSandbox:
    """获取 Shell 沙箱实例"""
    global _shell_sandbox
    if _shell_sandbox is None:
        _shell_sandbox = ShellSandbox()
    return _shell_sandbox


def execute_in_sandbox(code: str, language: str = "python", 
                      timeout: int = 60, use_sandbox: bool = True) -> Dict[str, Any]:
    """
    在沙箱中执行代码
    
    Args:
        code: 代码内容
        language: 编程语言（python 或 shell）
        timeout: 超时时间
        use_sandbox: 是否使用沙箱
        
    Returns:
        执行结果字典
    """
    # 先进行代码安全检查
    if language == "python":
        from hedera.core.code_checker import check_python_code_safety
        is_safe, violations = check_python_code_safety(code)
        if not is_safe:
            return {
                "stdout": "",
                "stderr": f"安全限制: 代码包含危险操作\n" + "\n".join(f"  - {v}" for v in violations),
                "returncode": -1,
                "success": False,
                "sandbox": True,
            }
    
    if not use_sandbox:
        # 不使用沙箱，直接执行（仅用于可信代码）
        if language == "python":
            from hedera.core.tools import _run_python
            return _run_python(code, timeout)
        else:
            from hedera.core.tools import _exec_shell
            return _exec_shell(code, timeout)
    
    # 使用沙箱执行
    if language == "python":
        sandbox = get_python_sandbox()
    else:
        sandbox = get_shell_sandbox()
    
    return sandbox.execute(code, timeout)


# 清理函数
def cleanup_sandboxes():
    """清理所有沙箱资源"""
    global _python_sandbox, _shell_sandbox
    
    if _python_sandbox:
        try:
            import shutil
            if _python_sandbox.config.temp_dir and os.path.exists(_python_sandbox.config.temp_dir):
                shutil.rmtree(_python_sandbox.config.temp_dir, ignore_errors=True)
        except Exception:
            pass
        _python_sandbox = None
    
    _shell_sandbox = None