"""
Hedera CLI — 交互式命令行界面
用法：python -m hedera chat 或 hedera chat
"""

import os
import sys
import json
import time
import threading
import requests

# Windows 控制台 UTF-8 支持
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ─── 颜色 ───
class C:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    RED = '\033[31m'
    GRAY = '\033[90m'
    WHITE = '\033[97m'

def _color(text, color):
    return f"{color}{text}{C.RESET}"

def _dim(text):
    return _color(text, C.DIM)

def _green(text):
    return _color(text, C.GREEN)

def _yellow(text):
    return _color(text, C.YELLOW)

def _blue(text):
    return _color(text, C.BLUE)

def _red(text):
    return _color(text, C.RED)

def _cyan(text):
    return _color(text, C.CYAN)


# ─── 配置 ───
DEFAULT_HOST = "http://localhost:36313"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".hedera")
TOKEN_FILE = os.path.join(CONFIG_DIR, "cli_token.json")


def _load_token():
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)
            if data.get("expires", 0) > time.time():
                return data.get("token")
    except Exception:
        pass
    return None


def _save_token(token, expires_in=3500):
    """保存 token（默认 3500 秒，比服务端 1 小时过期略短）"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump({"token": token, "expires": time.time() + expires_in}, f)


def _load_user_name():
    try:
        with open(os.path.join(CONFIG_DIR, "user_name.txt"), "r") as f:
            return f.read().strip()
    except Exception:
        return None


def _save_user_name(name):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(os.path.join(CONFIG_DIR, "user_name.txt"), "w") as f:
        f.write(name)


def _api(host, method, path, token=None, json_data=None, stream=False):
    """API 请求封装"""
    url = f"{host}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        if method == "GET":
            return requests.get(url, headers=headers, timeout=30)
        elif method == "POST":
            return requests.post(url, headers=headers, json=json_data, timeout=300, stream=stream)
        elif method == "DELETE":
            return requests.delete(url, headers=headers, timeout=30)
    except requests.ConnectionError:
        return None
    except Exception as e:
        return None


# ─── 命令处理 ───

def _print_help():
    print(f"""
{_cyan('Hedera CLI')} — 命令列表

  {_green('直接输入文字')}     发送消息
  {_green('/name <名称>')}    自定义用户名称
  {_green('/profile')}        查看可用人格
  {_green('/profile <名称>')} 切换人格（新建会话时生效）
  {_green('/createprofile')}  创建自定义人格
  {_green('/delprofile <名>')} 删除自定义人格
  {_green('/new')}            新建会话
  {_green('/list')}           列出所有会话
  {_green('/switch <id>')}    切换会话
  {_green('/delete <id>')}    删除会话
  {_green('/clear')}          清屏
  {_green('/config')}         查看当前配置
  {_green('/config <k> <v>')} 修改配置
  {_green('/presets')}        查看预设列表
  {_green('/apply <name>')}   应用预设
  {_green('/status')}         检查服务器状态
  {_green('/help')}           显示帮助
  {_green('/quit')}           退出
""")


def _get_terminal_size():
    """获取终端大小"""
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except Exception:
        return 80, 24


def _move_to(row, col):
    """移动光标到指定位置"""
    sys.stdout.write(f"\033[{row};{col}H")


def _clear_line():
    """清除当前行"""
    sys.stdout.write("\033[2K")


def _print_welcome():
    R = '\033[31m'  # 红色
    G = '\033[32m'  # 绿色
    print(f"""
{R}  ██╗  ██╗{G}███████╗{R}██████╗{G} ███████╗{R}██████╗ {G} █████╗ {C.RESET}
{R}  ██║  ██║{G}██╔════╝{R}██╔══██╗{G}██╔════╝{R}██╔══██╗{G}██╔══██╗{C.RESET}
{R}  ███████║{G}█████╗  {R}██║  ██║{G}█████╗  {R}███████╔{G}╝███████║{C.RESET}
{R}  ██╔══██║{G}██╔══╝  {R}██║  ██║{G}██╔══╝  {R}██╔══██╗{G}██╔══██║{C.RESET}
{R}  ██║  ██║{G}███████╗{R}██████╔╝{G}███████╗{R}██║  ██║{G}██║  ██║{C.RESET}
{R}  ╚═╝  ╚═╝{G}╚══════╝{R}╚═════╝ {G}╚══════╝{R}╚═╝  ╚═╝{G}╚═╝  ╚═╝{C.RESET}
  {_dim('v0.7.0')}  {_cyan('有性格的 AI Agent')}
  {_dim('输入 /help 查看命令，直接输入文字开始对话')}
""")


def _format_tool_call(name, args, status):
    """格式化工具调用显示"""
    icon = "..." if status == "running" else "[OK]" if status == "success" else "[!]"
    args_str = ""
    if args:
        vals = [str(v)[:30] for v in args.values() if isinstance(v, (str, int, float))]
        if vals:
            args_str = f" ({', '.join(vals[:2])})"
    return f"  {_dim(f'{icon} {name}{args_str}')}"


def _format_token_usage(usage):
    """格式化 token 用量显示"""
    if not usage:
        return ""
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    total = usage.get("total_tokens", 0)
    if total == 0:
        return ""
    return f"  {_dim(f'tokens: {prompt} in + {completion} out = {total} total')}"


# 全局状态：当前正在执行的工具名
_current_tool = ["思考中"]


def _spinner(stop_event):
    """加载动画（显示当前操作）"""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while not stop_event.is_set():
        msg = _current_tool[0]
        sys.stdout.write(f"\r  {_cyan(frames[i % len(frames)])} {_dim(msg)}...")
        sys.stdout.flush()
        i += 1
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def _output_lines(lines):
    """输出多行文字"""
    for line in lines:
        print(line)


def _output_line(text):
    """输出一行文字"""
    print(text)


def _stream_chat(host, token, message, session_id):
    """流式发送消息并显示"""

    # 启动加载动画
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=_spinner, args=(stop_event,), daemon=True)
    spinner_thread.start()

    tool_shown = set()
    response_text = ""
    first_data = True

    resp = _api(host, "POST", "/chat", token,
                {"message": message, "session_id": session_id},
                stream=True)

    if resp is None:
        stop_event.set()
        spinner_thread.join(timeout=1)
        print(_red("  连接失败，请检查服务器是否运行"))
        return

    if resp.status_code == 401:
        stop_event.set()
        spinner_thread.join(timeout=1)
        print(_red("  登录已过期，请重新登录"))
        return

    if resp.status_code != 200:
        stop_event.set()
        spinner_thread.join(timeout=1)
        print(_red(f"  错误: HTTP {resp.status_code}"))
        return

    token_usage = None
    for line in resp.iter_lines(decode_unicode=True):
        # 收到第一个数据时停止动画
        if first_data:
            stop_event.set()
            spinner_thread.join(timeout=1)
            first_data = False
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type", "")

        if ev_type == "tool":
            name = ev.get("name", "")
            status = ev.get("status", "running")
            args = ev.get("args", {})
            error = ev.get("error", "")

            # 更新当前操作状态（给 spinner 用）
            if status == "running" and name != "report_progress":
                _current_tool[0] = name
            elif status == "success" and name != "report_progress":
                _current_tool[0] = "思考中"

            # 只显示一次工具调用（成功或失败时）
            key = f"{name}_{status}"
            if key not in tool_shown or status == "error":
                tool_shown.add(key)
                if name != "report_progress":
                    print(_format_tool_call(name, args, status))
                    if error:
                        print(_red(f"    错误: {error[:100]}"))

        elif ev_type == "result":
            response_text = ev.get("response", "")
            session_id = ev.get("session_id", session_id)
            token_usage = ev.get("usage")

        elif ev_type == "error":
            print(_red(f"  错误: {ev.get('error', '未知错误')}"))

    # 显示回复
    if response_text:
        print()
        # 简单的 Markdown 渲染
        lines = response_text.split('\n')
        for line in lines:
            if line.startswith('```'):
                print(_dim('    ─' * 12))
            elif line.startswith('# '):
                print(f"  {_cyan(line[2:])}")
            elif line.startswith('## '):
                print(f"  {_blue(line[3:])}")
            elif line.startswith('- ') or line.startswith('* '):
                print(f"  {line}")
            else:
                print(f"  {line}")

        # 显示 token 用量
        usage_line = _format_token_usage(token_usage)
        if usage_line:
            print(usage_line)


def cmd_login(host, password):
    """登录并获取 token"""
    resp = _api(host, "POST", "/login", json_data={"password": password})
    if resp and resp.status_code == 200:
        data = resp.json()
        token = data.get("token")
        if token:
            _save_token(token)
            return token
    return None


def cmd_list_sessions(host, token):
    """列出所有会话"""
    resp = _api(host, "GET", "/sessions", token)
    if resp and resp.status_code == 200:
        data = resp.json()
        sessions = data.get("sessions", [])
        if not sessions:
            print(_dim("  暂无会话"))
            return
        print(f"\n  {_cyan('会话列表')} ({len(sessions)} 个)\n")
        for s in sessions:
            sid = s.get("session_id", "")
            title = s.get("title", "") or sid
            msgs = s.get("message_count", 0)
            profile = s.get("profile", "") or "默认"
            print(f"  {_green(sid)}  {title}  {_dim(f'({msgs}条, {profile})')}")
        print()


def cmd_list_profiles(host, token):
    """列出所有人格"""
    resp = _api(host, "GET", "/api/profiles", token)
    if resp and resp.status_code == 200:
        data = resp.json()
        profiles = data.get("profiles", [])
        if not profiles:
            print(_dim("  暂无人格"))
            return
        print(f"\n  {_cyan('可用人格')}\n")
        for p in profiles:
            name = p.get("name", "")
            tag = p.get("tag", "")
            print(f"  {_green(name)}  {_dim(tag)}")
        print()


def cmd_new_session(host, token, profile=None):
    """新建会话（可指定人格）"""
    body = {}
    if profile:
        resp = _api(host, "GET", "/api/profiles", token)
        if resp and resp.status_code == 200:
            for p in resp.json().get("profiles", []):
                if p.get("name") == profile or p.get("file") == profile:
                    body["profile"] = p.get("file", "")
                    break
    resp = _api(host, "POST", "/sessions", token, body)
    if resp and resp.status_code == 200:
        data = resp.json()
        sid = data.get("session_id", "")
        pname = profile or "默认"
        print(_green(f"  + 新会话: {sid[:12]} ({pname})"))
        return sid
    return None


def cmd_create_profile(host, token):
    """交互式创建自定义人格"""
    print(f"\n  {_cyan('创建自定义人格')}\n")
    name = input(f"  {_cyan('人格名称: ')}").strip()
    if not name:
        print(_red("  名称不能为空"))
        return
    tag = input(f"  {_cyan('标签（逗号分隔，可跳过）: ')}").strip()
    print(f"  {_dim('说话风格（输入后回车，如：说话简洁，偶尔开玩笑）')}")
    style = input(f"  {_cyan('> ')}").strip()
    print(f"  {_dim('核心准则（输入后回车，如：永远说实话）')}")
    rules = input(f"  {_cyan('> ')}").strip()

    body = {"name": name, "tag": tag, "style": style, "personality": rules}
    resp = _api(host, "POST", "/api/profiles/create", token, body)
    if resp and resp.status_code == 200:
        d = resp.json()
        if d.get("status") == "ok":
            print(_green(f"  + 已创建人格: {d.get('name', name)}"))
        else:
            print(_red(f"  创建失败: {d.get('error', '')}"))
    else:
        print(_red("  创建失败"))


def cmd_delete_profile(host, token, name):
    """删除自定义人格"""
    if not name:
        print(_red("  用法: /delprofile <名称>"))
        return
    resp = _api(host, "DELETE", f"/api/profiles/{name}", token)
    if resp and resp.status_code == 200:
        d = resp.json()
        if d.get("status") == "ok":
            print(_green(f"  + 已删除人格: {d.get('name', name)}"))
        else:
            print(_red(f"  删除失败: {d.get('error', '')}"))
    else:
        print(_red("  删除失败（可能不存在或是默认人格）"))


def cmd_config(host, token, key=None, value=None):
    """查看或修改配置"""
    if key and value:
        # 修改配置
        body = {}
        if key == "model.name":
            body["model_name"] = value
        elif key == "model.endpoint":
            body["model_endpoint"] = value
        elif key == "model.api_key":
            body["model_api_key"] = value
        else:
            print(_red(f"  不支持的配置项: {key}"))
            return
        resp = _api(host, "POST", "/config", token, body)
        if resp and resp.status_code == 200:
            # 重载配置
            _api(host, "POST", "/config/reload", token)
            print(_green(f"  + 已更新 {key}"))
        else:
            print(_red("  保存失败"))
    else:
        # 查看配置
        resp = _api(host, "GET", "/config", token)
        if resp and resp.status_code == 200:
            d = resp.json()
            m = d.get("model", {})
            print(f"""
  {_cyan('当前配置')}
  模型: {m.get('name', '?')}
  端点: {m.get('endpoint', '?')}
  Key:  {m.get('api_key_masked', '?')}
  上下文: {d.get('context_window', '?')}
""")


def cmd_presets(host, token):
    """查看预设列表"""
    resp = _api(host, "GET", "/api/presets", token)
    if resp and resp.status_code == 200:
        data = resp.json()
        presets = data.get("presets", {})
        for cat in ["llm", "img", "tts"]:
            items = presets.get(cat, [])
            print(f"\n  {_cyan(cat.upper())} 预设 ({len(items)} 个)")
            for p in items:
                print(f"    {p.get('name', '?')}")


def cmd_apply_preset(host, token, name):
    """应用预设"""
    # 先查找预设
    resp = _api(host, "GET", "/api/presets", token)
    if not resp or resp.status_code != 200:
        print(_red("  获取预设失败"))
        return

    data = resp.json()
    for cat in ["llm", "img", "tts"]:
        for p in data.get("presets", {}).get(cat, []):
            if p.get("name") == name:
                # 应用预设
                resp2 = _api(host, "POST", "/api/presets/apply", token,
                            {"name": name, "category": cat})
                if resp2 and resp2.status_code == 200:
                    _api(host, "POST", "/config/reload", token)
                    print(_green(f"  + 已应用: {name} ({cat})"))
                else:
                    print(_red("  应用失败"))
                return
    print(_red(f"  预设不存在: {name}"))


# ─── 主循环 ───

def run_cli(host=None, password=None, session=None, cmd=None, cmd_args=None):
    """直接调用 CLI（供 __main__.py 使用）"""
    _run_cli(
        host=host or DEFAULT_HOST,
        password=password,
        session=session,
        cmd=cmd,
        cmd_args=cmd_args or [],
    )


def main():
    """独立运行 CLI（hedera chat 或 python -m hedera chat）"""
    import argparse

    parser = argparse.ArgumentParser(description="Hedera CLI")
    parser.add_argument("--host", default=DEFAULT_HOST, help="服务器地址")
    parser.add_argument("--password", "-p", help="登录密码")
    parser.add_argument("--session", "-s", help="会话 ID")
    parser.add_argument("cmd", nargs="?", help="直接执行命令")
    parser.add_argument("cmd_args", nargs="*", help="命令参数")
    args = parser.parse_args()

    _run_cli(
        host=args.host,
        password=args.password,
        session=args.session,
        cmd=args.cmd,
        cmd_args=args.cmd_args or [],
    )


def _run_cli(host, password=None, session=None, cmd=None, cmd_args=None):
    """CLI 核心逻辑"""

    # 检查服务器
    resp = _api(host, "GET", "/health")
    if resp is None or resp.status_code != 200:
        print(_red("  无法连接到 Hedera 服务器"))
        print(_dim(f"  请确保服务器运行在 {host}"))
        sys.exit(1)

    # 登录（验证 token 是否有效）
    token = _load_token()
    if token:
        # 验证 token 是否仍然有效
        test_resp = _api(host, "GET", "/sessions", token)
        if test_resp is None or test_resp.status_code == 401:
            token = None  # token 无效，需要重新登录

    if not token:
        if not password:
            print(_dim("  登录已过期，请重新登录"))
            password = input(f"  {_cyan('密码: ')}")
        token = cmd_login(host, password)
        if not token:
            print(_red("  登录失败"))
            sys.exit(1)
        print(_green("  + 已登录"))

    # 用户名称（可通过 /name 修改）
    user_name = _load_user_name() or "user"

    # 单次命令模式
    if cmd:
        if cmd == "list":
            cmd_list_sessions(host, token)
        elif cmd == "profiles":
            cmd_list_profiles(host, token)
        elif cmd == "config":
            if len(cmd_args) >= 2:
                cmd_config(host, token, cmd_args[0], cmd_args[1])
            else:
                cmd_config(host, token)
        elif cmd == "presets":
            cmd_presets(host, token)
        elif cmd == "status":
            print(_green("  + 服务器运行中"))
        else:
            print(_red(f"  未知命令: {cmd}"))
        return

    # 交互模式
    _print_welcome()

    session_id = session or ""
    if not session_id:
        # 自动创建会话
        resp = _api(host, "POST", "/sessions", token, {})
        if resp and resp.status_code == 200:
            session_id = resp.json().get("session_id", "")

    # 显示当前状态
    resp = _api(host, "GET", f"/sessions/{session_id}", token)
    if resp and resp.status_code == 200:
        s = resp.json()
        sname = s.get("title", "") or session_id[:12]
        smodel = ""
        resp2 = _api(host, "GET", "/config", token)
        if resp2 and resp2.status_code == 200:
            smodel = resp2.json().get("model", {}).get("name", "")
        print(f"  {_dim('用户')} {_cyan(user_name)}  {_dim('|')}  {_dim('模型')} {_cyan(smodel)}  {_dim('|')}  {_dim('会话')} {_cyan(sname[:20])}")

    def _print_prompt():
        """显示输入提示（带上下分隔线）"""
        cols, rows = _get_terminal_size()
        line = _dim('─' * (cols - 4))
        # 输出区和输入区之间加分隔线
        print()
        print(f"  {line}")
        # 提示行
        sys.stdout.write(f"  {_cyan(user_name)} {_green('>')}")
        sys.stdout.flush()

    _print_prompt()
    while True:
        try:
            user_input = input().strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n  {_dim('再见')}")
            break

        if not user_input:
            _print_prompt()
            continue

        # 命令处理
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/quit", "/exit", "/q"):
                print(f"  {_dim('再见')}")
                break
            elif cmd == "/help":
                _print_help()
            elif cmd == "/name":
                if arg:
                    user_name = arg
                    _save_user_name(user_name)
                    print(_green(f"  + 用户名已改为: {user_name}"))
                else:
                    print(_dim(f"  当前用户名: {user_name}"))
                    print(_dim("  用法: /name <名称>"))
            elif cmd == "/profile":
                if arg:
                    # 切换人格（新建会话时生效）
                    new_sid = cmd_new_session(host, token, arg)
                    if new_sid:
                        session_id = new_sid
                else:
                    cmd_list_profiles(host, token)
            elif cmd == "/createprofile":
                cmd_create_profile(host, token)
            elif cmd == "/delprofile":
                cmd_delete_profile(host, token, arg)
            elif cmd == "/clear":
                os.system("cls" if os.name == "nt" else "clear")
                _print_welcome()
            elif cmd == "/new":
                new_sid = cmd_new_session(host, token, arg if arg else None)
                if new_sid:
                    session_id = new_sid
            elif cmd == "/list":
                cmd_list_sessions(host, token)
            elif cmd == "/switch":
                if arg:
                    session_id = arg
                    resp = _api(host, "GET", f"/sessions/{arg}", token)
                    sname = arg[:12]
                    if resp and resp.status_code == 200:
                        sname = resp.json().get("title", "") or arg[:12]
                    print(_green(f"  + 已切换: {sname}"))
                else:
                    print(_red("  用法: /switch <session_id>"))
            elif cmd == "/delete":
                if arg:
                    resp = _api(host, "DELETE", f"/sessions/{arg}", token)
                    if resp and resp.status_code == 200:
                        print(_green(f"  + 已删除: {arg[:12]}"))
                        if arg == session_id:
                            session_id = ""
                    else:
                        print(_red("  删除失败"))
                else:
                    print(_red("  用法: /delete <session_id>"))
            elif cmd == "/config":
                parts2 = arg.split(maxsplit=1) if arg else []
                if len(parts2) >= 2:
                    cmd_config(host, token, parts2[0], parts2[1])
                else:
                    cmd_config(host, token)
            elif cmd == "/presets":
                cmd_presets(host, token)
            elif cmd == "/apply":
                if arg:
                    cmd_apply_preset(host, token, arg)
                else:
                    print(_red("  用法: /apply <预设名>"))
            elif cmd == "/status":
                print(_green("  + 服务器运行中"))
            else:
                print(_red(f"  未知命令: {cmd}，输入 /help 查看帮助"))
            _print_prompt()
            continue

        # 发送消息
        if not session_id:
            resp = _api(host, "POST", "/sessions", token, {})
            if resp and resp.status_code == 200:
                session_id = resp.json().get("session_id", "")

        _stream_chat(host, token, user_input, session_id)
        _print_prompt()


if __name__ == "__main__":
    main()
