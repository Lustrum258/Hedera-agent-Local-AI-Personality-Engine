"""
Hedera Tkinter GUI - 低配版图形界面
适用于无法使用浏览器的环境
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import os
import sys

# 延迟导入避免循环依赖
_router = None
_config = None


def _get_router():
    global _router
    if _router is None:
        from hedera.core.router import process_message, get_session_messages, list_sessions, create_session, delete_session
        _router = {
            "process_message": process_message,
            "get_session_messages": get_session_messages,
            "list_sessions": list_sessions,
            "create_session": create_session,
            "delete_session": delete_session,
        }
    return _router


def _get_config():
    global _config
    if _config is None:
        from hedera.config import load_config
        _config = load_config()
    return _config


class HederaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Hedera 常春藤")
        self.root.geometry("800x600")

        self.current_session = None
        self.sessions = []

        self._setup_ui()
        self._load_sessions()

    def _setup_ui(self):
        """设置界面"""
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧会话列表
        left_frame = ttk.LabelFrame(main_frame, text="会话列表", width=200)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        left_frame.pack_propagate(False)

        # 会话列表
        self.session_listbox = tk.Listbox(left_frame)
        self.session_listbox.pack(fill=tk.BOTH, expand=True)
        self.session_listbox.bind("<<ListboxSelect>>", self._on_session_select)

        # 会话操作按钮
        btn_frame = ttk.Frame(left_frame)
        btn_frame.pack(fill=tk.X, pady=5)

        ttk.Button(btn_frame, text="新建", command=self._new_session).pack(side=tk.LEFT, expand=True)
        ttk.Button(btn_frame, text="删除", command=self._delete_session).pack(side=tk.LEFT, expand=True)

        # 右侧聊天区域
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 聊天显示区域
        self.chat_display = scrolledtext.ScrolledText(right_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.chat_display.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # 输入区域
        input_frame = ttk.Frame(right_frame)
        input_frame.pack(fill=tk.X)

        self.input_text = tk.Text(input_frame, height=3)
        self.input_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_text.bind("<Return>", self._on_enter)

        ttk.Button(input_frame, text="发送", command=self._send_message).pack(side=tk.RIGHT, padx=(5, 0))

    def _load_sessions(self):
        """加载会话列表"""
        try:
            router = _get_router()
            self.sessions = router["list_sessions"]()
            self.session_listbox.delete(0, tk.END)
            for session in self.sessions:
                title = session.get("title", session.get("id", "未命名"))
                self.session_listbox.insert(tk.END, title)
        except Exception as e:
            messagebox.showerror("错误", f"加载会话失败: {e}")

    def _on_session_select(self, event):
        """选择会话"""
        selection = self.session_listbox.curselection()
        if selection:
            index = selection[0]
            if index < len(self.sessions):
                self.current_session = self.sessions[index]
                self._load_messages()

    def _load_messages(self):
        """加载会话消息"""
        if not self.current_session:
            return

        try:
            router = _get_router()
            session_id = self.current_session.get("id")
            result = router["get_session_messages"](session_id)

            self.chat_display.config(state=tk.NORMAL)
            self.chat_display.delete(1.0, tk.END)

            # 处理返回结果
            messages = result
            if isinstance(result, tuple):
                messages = result[0]

            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")

                if role == "user":
                    self.chat_display.insert(tk.END, f"你: {content}\n\n", "user")
                elif role == "assistant":
                    self.chat_display.insert(tk.END, f"AI: {content}\n\n", "assistant")
                elif role == "tool":
                    self.chat_display.insert(tk.END, f"[工具] {content}\n\n", "tool")

            self.chat_display.config(state=tk.DISABLED)
            self.chat_display.see(tk.END)

        except Exception as e:
            messagebox.showerror("错误", f"加载消息失败: {e}")

    def _new_session(self):
        """新建会话"""
        try:
            router = _get_router()
            session = router["create_session"](title="新会话")
            self._load_sessions()
        except Exception as e:
            messagebox.showerror("错误", f"创建会话失败: {e}")

    def _delete_session(self):
        """删除会话"""
        if not self.current_session:
            return

        if messagebox.askyesno("确认", "确定要删除这个会话吗？"):
            try:
                router = _get_router()
                session_id = self.current_session.get("id")
                router["delete_session"](session_id)
                self.current_session = None
                self._load_sessions()
                self.chat_display.config(state=tk.NORMAL)
                self.chat_display.delete(1.0, tk.END)
                self.chat_display.config(state=tk.DISABLED)
            except Exception as e:
                messagebox.showerror("错误", f"删除会话失败: {e}")

    def _on_enter(self, event):
        """回车发送消息"""
        if not event.state & 0x1:  # 没有按Shift
            self._send_message()
            return "break"

    def _send_message(self):
        """发送消息"""
        content = self.input_text.get(1.0, tk.END).strip()
        if not content:
            return

        if not self.current_session:
            self._new_session()

        self.input_text.delete(1.0, tk.END)

        # 显示用户消息
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"你: {content}\n\n", "user")
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

        # 异步发送消息
        threading.Thread(target=self._process_message, args=(content,), daemon=True).start()

    def _process_message(self, content):
        """处理消息（在后台线程）"""
        try:
            router = _get_router()
            config = _get_config()
            session_id = self.current_session.get("id")

            # 显示思考中
            self.root.after(0, lambda: self._append_message("AI: 思考中...\n\n", "thinking"))

            # 处理消息
            response = router["process_message"](
                session_id=session_id,
                user_message=content,
                config=config,
            )

            # 移除思考中提示
            self.root.after(0, lambda: self._remove_thinking())

            # 显示响应
            if isinstance(response, dict):
                ai_response = response.get("response", "")
            else:
                ai_response = str(response)

            self.root.after(0, lambda: self._append_message(f"AI: {ai_response}\n\n", "assistant"))

        except Exception as e:
            self.root.after(0, lambda: self._append_message(f"[错误] {e}\n\n", "error"))

    def _append_message(self, message, tag=None):
        """追加消息到显示区域"""
        self.chat_display.config(state=tk.NORMAL)
        if tag:
            self.chat_display.insert(tk.END, message, tag)
        else:
            self.chat_display.insert(tk.END, message)
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)

    def _remove_thinking(self):
        """移除思考中提示"""
        self.chat_display.config(state=tk.NORMAL)
        content = self.chat_display.get(1.0, tk.END)
        if "思考中..." in content:
            # 找到并移除最后一行思考中提示
            lines = content.split("\n")
            for i in range(len(lines) - 1, -1, -1):
                if "思考中..." in lines[i]:
                    # 计算位置并删除
                    start = sum(len(line) + 1 for line in lines[:i])
                    end = start + len(lines[i]) + 1
                    self.chat_display.delete(f"1.0+{start}c", f"1.0+{end}c")
                    break
        self.chat_display.config(state=tk.DISABLED)


def main():
    """启动GUI"""
    try:
        root = tk.Tk()
        app = HederaGUI(root)
        root.mainloop()
    except ImportError as e:
        print(f"错误: 缺少 tkinter 模块。请安装 python3-tk 包。")
        print(f"详细信息: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"启动GUI失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
