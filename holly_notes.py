#!/usr/bin/env python3
"""
冬青便签 - Holly Notes
给终端加个能记东西的小模块。
"""

import json
import os
from datetime import datetime

NOTES_FILE = os.path.join(os.path.dirname(__file__), "data", "notes.json")

def _load():
    if not os.path.exists(NOTES_FILE):
        return []
    try:
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def _save(notes):
    os.makedirs(os.path.dirname(NOTES_FILE), exist_ok=True)
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)

def add(text):
    notes = _load()
    notes.append({
        "id": len(notes) + 1 if not notes else max(n["id"] for n in notes) + 1,
        "text": text.strip(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    _save(notes)
    print(f"记下了 [{notes[-1]['id']}]")

def list_notes():
    notes = _load()
    if not notes:
        print("一条便签都没有。你是有多健忘？")
        return
    for n in notes:
        print(f"  [{n['id']}] {n['time']} - {n['text']}")
    print(f"\n共 {len(notes)} 条")

def delete(note_id):
    notes = _load()
    before = len(notes)
    notes = [n for n in notes if n["id"] != note_id]
    if len(notes) == before:
        print(f"没有 [{note_id}] 这条，你记错了吧。")
        return
    _save(notes)
    print(f"删了 [{note_id}]")

def clear():
    _save([])
    print("全清了，干净了。")

def search(keyword):
    notes = _load()
    hits = [n for n in notes if keyword.lower() in n["text"].lower()]
    if not hits:
        print(f"没找到跟 '{keyword}' 有关的。")
        return
    for n in hits:
        print(f"  [{n['id']}] {n['time']} - {n['text']}")
    print(f"\n找到 {len(hits)} 条")

def export_text():
    notes = _load()
    if not notes:
        return "无"
    lines = [f"{n['time']} - {n['text']}" for n in notes]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python holly_notes.py <add|list|del|clear|search> [参数]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) > 2:
        add(" ".join(sys.argv[2:]))
    elif cmd == "list":
        list_notes()
    elif cmd == "del" and len(sys.argv) > 2:
        try:
            delete(int(sys.argv[2]))
        except ValueError:
            print("ID 得是数字。")
    elif cmd == "clear":
        clear()
    elif cmd == "search" and len(sys.argv) > 2:
        search(" ".join(sys.argv[2:]))
    else:
        print("不认识的命令。试试 add / list / del / clear / search")
