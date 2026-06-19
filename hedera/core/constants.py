"""
Hedera 常量配置
集中管理所有硬编码的魔法数字
"""

# ─── 超时设置 ───────────
DEFAULT_TIMEOUT = 120  # 默认超时（秒）
MAX_TIMEOUT = 600  # 最大超时（秒）
SHELL_TIMEOUT = 120  # Shell 命令超时（秒）
PYTHON_TIMEOUT = 120  # Python 执行超时（秒）
HTTP_TIMEOUT = 30  # HTTP 请求超时（秒）
UPLOAD_TIMEOUT = 300  # 文件上传超时（秒）

# ─── 输出限制 ───────────
MAX_OUTPUT_LENGTH = 30000  # 最大输出长度（字符）
TRUNCATE_SUFFIX = "\n...（结果过长已截断）"
TOOL_RESPONSE_MAX = 15000  # 工具响应最大长度
TOOL_RESPONSE_DEFAULT = 8000  # 工具响应默认长度

# ─── 上下文管理 ───────────
DEFAULT_CONTEXT_WINDOW = 32000  # 默认上下文窗口大小
DEFAULT_MAX_TOKENS = 8192  # 默认最大输出 token
HISTORY_LIMIT_SIMPLE = 50  # 简单任务历史消息限制
HISTORY_LIMIT_COMPLEX = 500  # 复杂任务历史消息限制
MAX_TOOL_LOOP = 20  # 最大工具调用循环次数

# ─── 安全限制 ───────────
MAX_COMMAND_LENGTH = 2000  # 最大命令长度
MAX_PATH_LENGTH = 260  # 最大路径长度（Windows）
MAX_FILENAME_LENGTH = 255  # 最大文件名长度

# ─── 代码执行安全 ───────────
BLOCKED_PYTHON_CALLS = [
    "os.system", "subprocess.call", "subprocess.run", "subprocess.Popen",
    "shutil.rmtree", "os.remove", "os.unlink", "eval(", "exec(",
    "os.popen", "os.exec", "os.spawn", "os.fork",
    "pty.spawn", "commands.getoutput",
]

BLOCKED_SHELL_COMMANDS = [
    "shutdown", "reboot", "rm -rf", "sudo", "su ",
    "mkfs", "dd if=", "format ", "del /f", "rd /s",
    "Invoke-Expression", "IEX(", "iex(",
    "> /dev/null", "> NUL", "2>&1",
]

BLOCKED_PATHS_READ = [
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "/etc", "/usr", "/var", "/root", "/boot",
    "~/.ssh", "~/.gnupg", "~/.aws", "~/.config",
]

BLOCKED_PATHS_WRITE = [
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "/etc", "/usr", "/var", "/root", "/boot", "/bin", "/sbin",
    "~/.ssh", "~/.gnupg", "~/.aws", "~/.config",
]

BLOCKED_URL_SCHEMES = [
    "file://", "javascript:", "data:", "ftp://", "ftps://",
]

# ─── 缓存设置 ───────────
CACHE_MAX_SIZE = 1000  # 缓存最大条目数
CACHE_TTL = 3600  # 缓存过期时间（秒）
SEARCH_CACHE_TTL = 1800  # 搜索缓存过期时间（秒）
FETCH_CACHE_TTL = 3600  # 网页缓存过期时间（秒）
FILE_CACHE_TTL = 7200  # 文件缓存过期时间（秒）

# ─── 自省和蒸馏 ───────────
REFLECTION_INTERVAL = 300  # 自省检查间隔（秒）
REFLECTION_MESSAGE_COUNT = 3  # 触发自省的消息数
DISTILL_INTERVAL = 1800  # 蒸馏检查间隔（秒）
DISTILL_COOLDOWN = 600  # 蒸馏后冷却时间（秒）
MAX_EXPERIENCE_RULES = 20  # 最大经验准则数
EXPERIENCE_EXPIRY_DAYS = 30  # 经验准则有效期（天）
BASELINE_PASS_THRESHOLD = 0.8  # 基线检查通过阈值

# ─── 跨会话记忆 ───────────
CROSS_SESSION_MAX = 5  # 跨会话最大会话数
CROSS_SESSION_MESSAGES = 1  # 每个会话提取消息数
LONG_TERM_MEMORY_LIMIT = 10  # 长期记忆最大条目数
LONG_TERM_MEMORY_MIN_IMPORTANCE = 4  # 长期记忆最小重要性

# ─── 文件操作 ───────────
MAX_FILE_SIZE = 100 * 1024 * 1024  # 最大文件大小（100MB）
MAX_LINES_READ = 2000  # 最大读取行数
MAX_LINES_WRITE = 10000  # 最大写入行数

# ─── 网页抓取 ───────────
MAX_WEB_CONTENT_LENGTH = 50000  # 最大网页内容长度
WEB_FETCH_TIMEOUT = 15  # 网页抓取超时（秒）
MAX_SEARCH_RESULTS = 10  # 最大搜索结果数

# ─── 测试运行 ───────────
TEST_TIMEOUT = 120  # 测试运行超时（秒）
MAX_TEST_OUTPUT = 10000  # 最大测试输出长度