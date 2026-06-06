"""
Hedera 输入校验 & 沙箱机制
"""

import os
import re

# ─── 路径安全 ───────────

# 项目可操作的安全根目录
_ALLOWED_ROOTS = [
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")),  # Desktop/hedera
    os.path.expanduser("~"),
]

# 明确禁止写入的系统路径（缩写列表，安全第一）
_BLOCKED_WRITE_PATHS = [
    os.path.normpath(p) for p in [
        "C:\\Windows",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
        "C:\\System32",
        "C:\\Users\\Administrator\\AppData",
        "/etc",
        "/usr",
        "/bin",
        "/boot",
        "/sys",
    ]
]


def sanitize_path(path: str, allow_any: bool = False) -> str | None:
    """
    校验路径安全性。
    - 阻止路径穿越（..）逃逸
    - 阻止写入系统关键目录
    - 返回规范化路径，非法返回 None
    """
    try:
        abs_path = os.path.normpath(os.path.abspath(path))
    except Exception:
        return None

    # 检查路径穿越：规范化后的路径不应包含 .. 段
    if ".." in path.split(os.sep):
        return None

    # 阻止写入系统关键目录
    for blocked in _BLOCKED_WRITE_PATHS:
        if abs_path.lower().startswith(blocked.lower()):
            return None

    return abs_path


def validate_read_path(path: str) -> str | None:
    """校验读路径"""
    return sanitize_path(path)


def validate_write_path(path: str) -> str | None:
    """校验写路径（更严格）"""
    abs_path = sanitize_path(path)
    if abs_path is None:
        return None
    # 不允许覆盖系统文件
    for blocked in _BLOCKED_WRITE_PATHS:
        if abs_path.lower().startswith(blocked.lower()):
            return None
    return abs_path


# ─── Shell 命令安全 ───────────

_BLOCKED_COMMANDS = [
    # 危险操作
    "shutdown", "reboot", "halt", "poweroff",
    "format", "fdisk", "mkfs", "dd",
    "chmod 777", "chown",
    # 删除/破坏
    "rm -rf", "rm -fr", "rmdir /s",
    "del /f /s", "rd /s /q",
    # 提权
    "sudo ", "su ", "runas",
    # 危险的 PowerShell
    "Invoke-Expression",
]

_BLOCKED_PATTERNS = [
    r">\s*NUL",                # 重定向到 NUL
    r">\s*/dev/null",
]

_SHELL_TIMEOUT_MAX = 600       # 最大超时上限（编码任务可能需要长时间编译）
_SHELL_OUTPUT_MAX = 30000      # 最大输出字符数（增加以支持长编译输出）


def validate_shell_command(cmd: str, timeout: int) -> dict | None:
    """
    校验 shell 命令合法性。
    返回 None 表示合法，返回 dict 含 error 信息表示不合法。
    """
    cmd_lower = cmd.lower().strip()

    # 空命令
    if not cmd:
        return {"success": False, "error": "命令为空"}

    # 命令长度限制
    if len(cmd) > 2000:
        return {"success": False, "error": "命令过长（超过 2000 字符）"}

    # 阻止危险命令
    for blocked in _BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return {"success": False, "error": f"阻止危险命令: 包含 '{blocked}'"}

    # 阻止危险模式
    for pat in _BLOCKED_PATTERNS:
        if re.search(pat, cmd):
            return {"success": False, "error": f"阻止危险模式: {pat}"}

    # 超时上限
    if timeout > _SHELL_TIMEOUT_MAX:
        return {"success": False, "error": f"超时不能超过 {_SHELL_TIMEOUT_MAX}s"}

    return None  # 合法


def truncate_output(text: str, max_chars: int = _SHELL_OUTPUT_MAX) -> str:
    """截断 shell 输出"""
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...（已截断，仅显示前 {max_chars} 字符）"
    return text


def get_blocked_patterns() -> list[str]:
    """返回当前阻止的命令列表（供 LLM 提示使用）"""
    return _BLOCKED_COMMANDS


# ─── URL 安全 ───────────

_BLOCKED_URL_PATTERNS = [
    r"^file://",
    r"^javascript:",
    r"^data:",
    r"^ftp://",
]


def validate_url(url: str) -> str | None:
    """校验 URL 合法性"""
    if not url or len(url) > 2048:
        return None
    url_lower = url.lower().strip()
    for pat in _BLOCKED_URL_PATTERNS:
        if re.match(pat, url_lower):
            return None
    # 必须是 http/https
    if not url_lower.startswith("http://") and not url_lower.startswith("https://"):
        return None
    return url


# ─── 插件沙箱（轻量） ───────────

import threading

_PLUGIN_TIMEOUT_SECONDS = 15


def run_plugin_safe(fn, args: dict, timeout: float = _PLUGIN_TIMEOUT_SECONDS) -> dict:
    """
    安全执行插件函数：超时保护 + 异常隔离。
    如果插件炸了或超时了，不影响主进程。
    """
    result_container = []
    exception_container = []

    def _run():
        try:
            result_container.append(fn(**args))
        except Exception as e:
            exception_container.append(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return {"success": False, "error": f"插件执行超时（{timeout}s）"}
    if exception_container:
        return {"success": False, "error": str(exception_container[0])}
    return result_container[0]
