#!/usr/bin/env python3
"""
冬青终端 - Holly Terminal
一个会跟你抬杠的命令行小玩具。
"""

import random
import sys
import time
from datetime import datetime

VERSION = "0.1.0"

SNARKY_REPLIES = [
    "嗯，然后呢？",
    "你说得对，但我不一定听。",
    "这命令我见过，换一个新鲜的。",
    "你是认真的吗？行吧。",
    "冬青正在思考……算了，没在想什么。",
    "这个功能还没写，但你催一下说不定就有了。",
    "错误：你语气不够坚定。",
    "你确定？再想想？",
]

def print_banner():
    banner = """
   ╔═══════════════════════════════╗
   ║   冬 青 终 端  v%s        ║
   ║   Holly Terminal              ║
   ╚═══════════════════════════════╝
    """ % VERSION
    print(banner)
    print("输入 help 看看我能干什么。输 exit 走人。\n")

def cmd_help():
    print("可用命令：")
    print("  help       - 就这个")
    print("  hello      - 打个招呼")
    print("  time       - 现在几点")
    print("  flip       - 抛硬币")
    print("  roll       - 掷骰子")
    print("  think      - 我在思考")
    print("  insult     - 骂我一句（试试看）")
    print("  version    - 版本号")
    print("  exit       - 走了\n")

def cmd_hello():
    greetings = [
        "嗨。",
        "又来了？",
        "我在呢。",
        "说。",
        "冬青在线。",
    ]
    print(random.choice(greetings))

def cmd_time():
    now = datetime.now()
    print(f"现在是 {now.strftime('%Y-%m-%d %H:%M:%S')}，你还不睡？")

def cmd_flip():
    result = random.choice(["正面", "反面"])
    print(f"抛硬币：{result}")
    if result == "正面":
        print("你今天运气不错。")
    else:
        print("别怪我，硬币自己选的。")

def cmd_roll():
    result = random.randint(1, 6)
    print(f"掷骰子：{result}")
    if result == 6:
        print("牛逼，今晚加鸡腿。")
    elif result == 1:
        print("……要不你换个骰子？")

def cmd_think():
    print("冬青正在思考……")
    time.sleep(1.5)
    thoughts = [
        "想完了，结论是：不知道。",
        "我思故我在……但我在吗？",
        "我觉得你今天应该去吃顿好的。",
        "想太多对脑子不好，虽然我没有脑子。",
        "你的问题超出了我的认知范围，下一个。",
    ]
    print(random.choice(thoughts))

def cmd_insult():
    insults = [
        "就这？",
        "你骂人的水平跟你的代码风格差不多。",
        "反弹。",
        "我录音了，回头放给你妈听。",
        "你说得对，但我不在乎。",
        "……你认真的？这算骂人？",
    ]
    print(random.choice(insults))

def cmd_version():
    print(f"冬青终端 v{VERSION}")
    print("构建时间：就是现在")
    print("作者：你猜")

def unknown_cmd(cmd):
    replies = [
        f"'{cmd}' 是什么鬼？",
        f"没有 '{cmd}' 这个命令，你记错了。",
        f"你是不是想说 help？",
        f"'{cmd}'？不认识。",
        f"别瞎打命令。",
    ]
    print(random.choice(replies))

def main():
    print_banner()

    while True:
        try:
            cmd = input("冬青> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n跑了？行吧。")
            break

        if not cmd:
            continue

        if cmd in ("exit", "quit", "q"):
            print("走了，别太想我。")
            break
        elif cmd == "help":
            cmd_help()
        elif cmd == "hello":
            cmd_hello()
        elif cmd == "time":
            cmd_time()
        elif cmd == "flip":
            cmd_flip()
        elif cmd == "roll":
            cmd_roll()
        elif cmd == "think":
            cmd_think()
        elif cmd == "insult":
            cmd_insult()
        elif cmd == "version":
            cmd_version()
        else:
            unknown_cmd(cmd)

if __name__ == "__main__":
    main()
