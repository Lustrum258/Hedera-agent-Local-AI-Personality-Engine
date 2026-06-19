"""
Hedera 代码安全检查器
使用 AST 解析进行严格的 Python 代码安全检查
"""

import ast
import re
from typing import Set, List, Tuple


class CodeSecurityError(Exception):
    """代码安全检查异常"""
    pass


class PythonSecurityChecker(ast.NodeVisitor):
    """Python AST 安全检查器"""
    
    # 危险的模块
    BLOCKED_MODULES = {
        'os', 'subprocess', 'shutil', 'sys', 'pty', 'commands',
        'signal', 'ctypes', 'importlib', 'code', 'codeop',
        'compile', 'compileall', 'py_compile',
    }
    
    # 危险的函数/方法
    BLOCKED_FUNCTIONS = {
        'system', 'popen', 'exec', 'eval', 'compile',
        'execfile', 'reload', 'input', 'raw_input',
        'open',  # 需要特殊处理
        'remove', 'unlink', 'rmdir', 'removedirs',
        'rename', 'renames', 'replace',
        'makedirs', 'mkdir', 'rmtree',
        'chmod', 'chown', 'chroot',
        'fork', 'execv', 'execve', 'spawnl', 'spawnlp',
        'system', 'popen', 'popen2', 'popen3', 'popen4',
        'call', 'check_call', 'check_output', 'run', 'Popen',
        'getoutput', 'getstatusoutput',
        'kill', 'terminate', 'send_signal',
    }
    
    # 危险的属性访问
    BLOCKED_ATTRIBUTES = {
        '__subclasses__', '__bases__', '__mro__', '__class__',
        '__globals__', '__locals__', '__builtins__', '__import__',
        '__loader__', '__spec__', '__file__', '__name__',
        '__qualname__', '__module__', '__dict__', '__weakref__',
        '__sizeof__', '__dir__', '__init_subclass__',
    }
    
    # 危险的内置函数
    BLOCKED_BUILTINS = {
        'eval', 'exec', 'compile', 'input', 'raw_input',
        'reload', 'exit', 'quit', 'help', 'license',
    }
    
    def __init__(self):
        self.violations: List[str] = []
        self.imported_modules: Set[str] = set()
        self.used_functions: Set[str] = set()
    
    def check(self, code: str) -> Tuple[bool, List[str]]:
        """检查代码安全性，返回 (是否安全, 违规列表)"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, [f"语法错误: {e}"]
        
        self.visit(tree)
        
        # 检查导入的危险模块
        dangerous_imports = self.imported_modules & self.BLOCKED_MODULES
        if dangerous_imports:
            self.violations.append(f"禁止导入模块: {', '.join(dangerous_imports)}")
        
        # 检查危险函数调用
        dangerous_calls = self.used_functions & self.BLOCKED_FUNCTIONS
        if dangerous_calls:
            self.violations.append(f"禁止调用函数: {', '.join(dangerous_calls)}")
        
        return len(self.violations) == 0, self.violations
    
    def visit_Import(self, node):
        """检查 import 语句"""
        for alias in node.names:
            module = alias.name.split('.')[0]  # 取顶层模块名
            self.imported_modules.add(module)
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node):
        """检查 from ... import 语句"""
        if node.module:
            module = node.module.split('.')[0]
            self.imported_modules.add(module)
            
            # 检查导入的具体函数
            for alias in node.names:
                if alias.name in self.BLOCKED_FUNCTIONS:
                    self.violations.append(
                        f"禁止从 {node.module} 导入 {alias.name}"
                    )
        self.generic_visit(node)
    
    def visit_Call(self, node):
        """检查函数调用"""
        # 检查直接函数调用
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in self.BLOCKED_FUNCTIONS:
                self.used_functions.add(func_name)
        
        # 检查方法调用
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in self.BLOCKED_FUNCTIONS:
                self.used_functions.add(attr_name)
            
            # 检查危险属性访问
            if attr_name in self.BLOCKED_ATTRIBUTES:
                self.violations.append(f"禁止访问属性: {attr_name}")
        
        # 检查内置函数
        if isinstance(node.func, ast.Name) and node.func.id in self.BLOCKED_BUILTINS:
            self.violations.append(f"禁止调用内置函数: {node.func.id}")
        
        self.generic_visit(node)
    
    def visit_Attribute(self, node):
        """检查属性访问"""
        if node.attr in self.BLOCKED_ATTRIBUTES:
            self.violations.append(f"禁止访问属性: {node.attr}")
        self.generic_visit(node)
    
    def visit_Exec(self, node):
        """检查 exec 语句（Python 2 兼容）"""
        self.violations.append("禁止使用 exec 语句")
        self.generic_visit(node)
    
    def visit_Delete(self, node):
        """检查 del 语句"""
        # 禁止删除重要对象
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id in ('__builtins__', '__globals__', '__locals__'):
                    self.violations.append(f"禁止删除: {target.id}")
        self.generic_visit(node)


def check_python_code_safety(code: str) -> Tuple[bool, List[str]]:
    """
    检查 Python 代码安全性
    
    Args:
        code: Python 代码字符串
        
    Returns:
        (是否安全, 违规列表)
    """
    # 1. 基本字符串检查（快速过滤）
    basic_violations = _basic_string_check(code)
    if basic_violations:
        return False, basic_violations
    
    # 2. AST 解析检查（精确检查）
    checker = PythonSecurityChecker()
    is_safe, violations = checker.check(code)
    
    return is_safe, violations


def _basic_string_check(code: str) -> List[str]:
    """基本字符串检查，快速过滤明显违规"""
    violations = []
    code_lower = code.lower()
    
    # 检查危险模块导入
    dangerous_imports = [
        'import os', 'import subprocess', 'import shutil', 'import sys',
        'import pty', 'import commands', 'import signal', 'import ctypes',
        'from os', 'from subprocess', 'from shutil', 'from sys',
    ]
    for imp in dangerous_imports:
        if imp in code_lower:
            violations.append(f"检测到危险导入: {imp}")
    
    # 检查危险函数调用
    dangerous_calls = [
        'os.system', 'subprocess.call', 'subprocess.run', 'subprocess.popen',
        'shutil.rmtree', 'os.remove', 'os.unlink', 'eval(', 'exec(',
        'os.popen', 'os.exec', 'os.spawn', 'os.fork',
        'pty.spawn', 'commands.getoutput',
    ]
    for call in dangerous_calls:
        if call in code_lower:
            violations.append(f"检测到危险调用: {call}")
    
    # 检查危险属性访问
    dangerous_attrs = [
        '__subclasses__', '__bases__', '__mro__', '__class__',
        '__globals__', '__locals__', '__builtins__', '__import__',
    ]
    for attr in dangerous_attrs:
        if attr in code_lower:
            violations.append(f"检测到危险属性访问: {attr}")
    
    return violations


def sanitize_code_for_display(code: str, max_length: int = 200) -> str:
    """清理代码用于显示，截断过长的代码"""
    if len(code) <= max_length:
        return code
    return code[:max_length] + "..."


# 测试函数
if __name__ == "__main__":
    # 测试安全代码
    safe_code = """
import math
result = math.sqrt(16)
print(f"结果: {result}")
"""
    
    # 测试危险代码
    dangerous_code = """
import os
os.system("rm -rf /")
"""
    
    print("测试安全代码:")
    is_safe, violations = check_python_code_safety(safe_code)
    print(f"安全: {is_safe}, 违规: {violations}")
    
    print("\n测试危险代码:")
    is_safe, violations = check_python_code_safety(dangerous_code)
    print(f"安全: {is_safe}, 违规: {violations}")