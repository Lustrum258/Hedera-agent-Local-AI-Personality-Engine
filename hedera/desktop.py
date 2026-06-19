"""
Hedera Desktop — Edge App 模式
用 Edge 的 --app 模式创建原生外观窗口，无需 pywebview
"""

import os
import sys
import threading
import time
import json
import urllib.request
import subprocess
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
CWD = os.getcwd()
CONFIG_PATH = os.path.join(CWD, "config.yaml")
if not os.path.exists(CONFIG_PATH):
    CONFIG_PATH = os.path.join(HERE, "config.yaml")


def start_server():
    # 初始化安全组件
    from hedera.core.init import init_security, cleanup_security
    from hedera.config import get_data_dir, load_config
    
    config = load_config(CONFIG_PATH)
    data_dir = get_data_dir(config)
    
    # 初始化安全组件
    init_security(data_dir)
    
    # 注册清理函数
    import atexit
    atexit.register(cleanup_security)
    
    # 启动服务器
    from hedera.server.http import run_server
    run_server(CONFIG_PATH)


def find_edge():
    """Find Edge executable"""
    paths = [
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in paths:
        expanded = os.path.expandvars(p)
        if os.path.exists(expanded):
            return expanded

    # Fallback: try PATH
    import shutil
    edge = shutil.which("msedge")
    if edge:
        return edge

    # Last resort
    return "msedge.exe"


def wait_for_server(port=36313, timeout=15):
    for i in range(timeout * 2):
        time.sleep(0.5)
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
            return json.loads(r.read().decode()).get("status") == "ok"
        except:
            pass
    return False


def main():
    port = 36313
    password = "hedera2024"
    try:
        import yaml
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        port = cfg.get("server", {}).get("port", 36313)
        password = cfg.get("server", {}).get("password", "hedera2024")
    except:
        pass

    # Check if already running
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        if json.loads(r.read().decode()).get("status") == "ok":
            pass  # already running
        else:
            raise Exception()
    except:
        # Start server in background
        t = threading.Thread(target=start_server, daemon=True)
        t.start()
        if not wait_for_server(port=port):
            print("Hedera: Service failed to start")
            return

    # Open default browser
    url = f"http://127.0.0.1:{port}"
    try:
        webbrowser.open(url)
    except:
        try:
            subprocess.Popen(["cmd", "/c", "start", url], shell=True)
        except:
            pass

    print(f"Hedera running at {url}")
    print(f"Password: {password}")
    print("Close this window to stop the server.")

    # Keep process alive
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
