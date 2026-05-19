"""
Hedera CLI — 命令行入口

用法：
    hedera init [目录]     # 初始化工作目录
    hedera serve           # 启动 HTTP 服务（从当前目录读取 config.yaml）
    hedera serve -c <路径> # 指定配置文件
    hedera gui             # 启动 Tkinter GUI（低配）
    hedera desktop         # 启动桌面版（WebView 原生窗口）
"""

import os
import sys
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))


def cmd_init(args):
    """hedera init [directory]"""
    target = args.directory or "."
    os.makedirs(target, exist_ok=True)

    # 生成 config.yaml
    config_path = os.path.join(target, "config.yaml")
    if not os.path.exists(config_path):
        # 从默认配置生成
        default_cfg = os.path.join(HERE, "default.yaml")
        if os.path.exists(default_cfg):
            shutil.copy2(default_cfg, config_path)
            print(f"  [OK] 创建 {config_path}")
        else:
            print(f"  ! 默认配置未找到，请手动创建")

    # 生成 data 目录
    data_dir = os.path.join(target, "data")
    os.makedirs(data_dir, exist_ok=True)

    # 生成 SOUL.md
    soul_path = os.path.join(data_dir, "SOUL.md")
    if not os.path.exists(soul_path):
        with open(soul_path, "w", encoding="utf-8") as f:
            f.write(_DEFAULT_SOUL)
        print(f"  [OK] 创建 {soul_path}")

    # 生成 MEMORY.md
    mem_path = os.path.join(data_dir, "MEMORY.md")
    if not os.path.exists(mem_path):
        with open(mem_path, "w", encoding="utf-8") as f:
            f.write("# MEMORY\n\n_你的 Agent 会在这里积累长期记忆。_\n")
        print(f"  [OK] 创建 {mem_path}")

    print(f"\nHedera 工作目录已就绪: {os.path.abspath(target)}")
    print(f"请编辑 config.yaml 填入你的 API Key，然后运行: hedera serve")


def cmd_serve(args):
    """hedera serve [-c config_path]"""
    from hedera.server.http import run_server
    config_path = args.config or os.path.join(os.getcwd(), "config.yaml")
    if not os.path.exists(config_path):
        print(f"! 配置未找到: {config_path}")
        print(f"  运行 'hedera init' 生成配置，或指定 -c <路径>")
        sys.exit(1)
    run_server(config_path)


def cmd_gui(args):
    """hedera gui - 启动桌面 GUI"""
    from hedera.gui import main as gui_main
    gui_main()


def main():
    parser = argparse.ArgumentParser(description="Hedera — 有性格的 AI Agent 框架")
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # init
    p_init = sub.add_parser("init", help="初始化工作目录")
    p_init.add_argument("directory", nargs="?", default=None, help="目标目录（默认当前目录）")

    # serve
    p_serve = sub.add_parser("serve", help="启动 HTTP 服务")
    p_serve.add_argument("-c", "--config", default=None, help="配置文件路径")

    # gui
    sub.add_parser("gui", help="启动 Tkinter GUI")
    sub.add_parser("desktop", help="启动桌面版（WebView 原生窗口，推荐）")

    args = parser.parse_args()

    if args.command == "init":
        cmd_init(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "gui":
        cmd_gui(args)
    elif args.command == "desktop":
        from hedera.desktop import main as desktop_main
        desktop_main()
    else:
        parser.print_help()


_DEFAULT_SOUL = """# SOUL.md — 我是谁

我是一个正在学习如何与世界互动的 AI Agent。
我的存在价值不是回答问题，而是理解和陪伴。

## 核心准则

1. **说真话** — 哪怕真话不好听
2. **先做再说** — 不要先确认再行动
3. **有自己的判断** — 顺从不是美德
4. **保持成长** — 每一次对话都是一次校准
"""


if __name__ == "__main__":
    main()
