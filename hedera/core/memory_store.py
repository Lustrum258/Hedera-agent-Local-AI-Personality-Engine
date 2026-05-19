"""
Hedera 持久化记忆系统 (SQLite)
"""

import os
import sqlite3
import json
import datetime
import threading
from typing import Optional

_db_lock = threading.Lock()


class MemoryStore:
    def __init__(self, db_dir: str, session_id: str = None):
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, "hedera.db")
        self.session_id = session_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._init_db()
        self._ensure_session()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                title TEXT DEFAULT '',
                profile TEXT DEFAULT '',
                started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                ended_at TEXT,
                message_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                task_type TEXT DEFAULT 'unknown',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS slider_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                processing REAL, thinking REAL, drive REAL,
                goal REAL, correction REAL, value REAL,
                snapped_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                importance INTEGER DEFAULT 5,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_ltm_key ON long_term_memory(key);
            CREATE TABLE IF NOT EXISTS file_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                message_rowid INTEGER DEFAULT 0,
                filename TEXT NOT NULL,
                url TEXT NOT NULL,
                size INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
        """)
        # 迁移：旧数据库添加缺失的列
        for col in ['title', 'profile']:
            try:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT DEFAULT ''")
                conn.commit()
            except Exception:
                pass
        # 迁移：file_links 表添加 message_rowid
        try:
            conn.execute("ALTER TABLE file_links ADD COLUMN message_rowid INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass
        conn.commit()
        conn.close()

    def _ensure_session(self):
        conn = self._get_conn()
        conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (self.session_id,))
        conn.commit()
        conn.close()

    def save_message(self, role: str, content: str, task_type: str = "unknown", return_rowid: bool = False) -> int:
        """保存消息。return_rowid=True 时返回插入的行ID。"""
        with _db_lock:
            conn = self._get_conn()
            if role == "user":
                cur = conn.execute("SELECT title, message_count FROM sessions WHERE session_id = ?", (self.session_id,))
                row = cur.fetchone()
                if row and not row["title"] and row["message_count"] == 0 and content.strip():
                    title = content.strip()[:40]
                    if len(content.strip()) > 40:
                        title += "..."
                    conn.execute("UPDATE sessions SET title = ? WHERE session_id = ?", (title, self.session_id))
            conn.execute(
                "INSERT INTO messages (session_id, role, content, task_type) VALUES (?, ?, ?, ?)",
                (self.session_id, role, content, task_type)
            )
            conn.execute("UPDATE sessions SET message_count = message_count + 1 WHERE session_id = ?",
                         (self.session_id,))
            conn.commit()
            last_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.close()
            return last_id if return_rowid else 0

    def save_message_pair(self, user_msg: str, assistant_msg: str, user_task: str = "unknown", assistant_task: str = "unknown"):
        """原子保存一对用户/助手消息。要么都存上，要么都不存。"""
        with _db_lock:
            conn = self._get_conn()
            try:
                # 首条消息自动命名
                cur = conn.execute("SELECT title, message_count FROM sessions WHERE session_id = ?", (self.session_id,))
                row = cur.fetchone()
                if row and not row["title"] and row["message_count"] == 0 and user_msg.strip():
                    title = user_msg.strip()[:40]
                    if len(user_msg.strip()) > 40:
                        title += "..."
                    conn.execute("UPDATE sessions SET title = ? WHERE session_id = ?", (title, self.session_id))
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, task_type) VALUES (?, ?, ?, ?)",
                    (self.session_id, "user", user_msg, user_task)
                )
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, task_type) VALUES (?, ?, ?, ?)",
                    (self.session_id, "assistant", assistant_msg, assistant_task)
                )
                conn.execute("UPDATE sessions SET message_count = message_count + 2 WHERE session_id = ?",
                             (self.session_id,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def save_checkpoint(self, data: dict):
        """保存恢复点，用于工具循环中断后恢复。"""
        with _db_lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, task_type) VALUES (?, ?, ?, ?)",
                    (self.session_id, "system", f"[CHECKPOINT] {json.dumps(data, ensure_ascii=False)[:2000]}", "checkpoint")
                )
                conn.commit()
            except Exception:
                conn.rollback()
            finally:
                conn.close()

    def get_last_checkpoint(self) -> dict | None:
        """获取最近的恢复点"""
        with _db_lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT content FROM messages WHERE session_id = ? AND task_type = 'checkpoint' ORDER BY id DESC LIMIT 1",
                    (self.session_id,)
                ).fetchone()
                conn.close()
                if row:
                    raw = row["content"]
                    if raw.startswith("[CHECKPOINT] "):
                        return json.loads(raw[13:])
                return None
            except Exception:
                conn.close()
                return None

    def get_recent_history(self, limit: int = 20) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT role, content, task_type, created_at FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (self.session_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]

    # ─── 会话管理 ───

    def list_sessions(self) -> list[dict]:
        """列出所有会话，按最近活跃排序"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT s.session_id, s.title, s.profile, s.started_at, s.ended_at, s.message_count, "
            "(SELECT MAX(created_at) FROM messages m WHERE m.session_id = s.session_id) AS last_active "
            "FROM sessions s ORDER BY last_active DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_session(self, session_id: str = None, title: str = "", profile: str = "") -> str:
        """创建新会话，返回 session_id。profile 为人格文件名（如 茯苓.md）"""
        sid = session_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO sessions (session_id, title, profile) VALUES (?, ?, ?)",
                (sid, title, profile)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        conn.close()
        return sid

    def get_session_info(self, session_id: str) -> dict:
        """获取单个会话信息"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT s.session_id, s.title, s.profile, s.started_at, s.ended_at, s.message_count, "
            "(SELECT MAX(created_at) FROM messages m WHERE m.session_id = s.session_id) AS last_active "
            "FROM sessions s WHERE s.session_id = ?", (session_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_session_messages(self, session_id: str, limit: int = 100) -> tuple:
        """获取指定会话的消息历史。返回 (messages, files_by_rowid)"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, role, content, task_type, created_at FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit)
        ).fetchall()
        # Also get file links
        file_rows = conn.execute(
            "SELECT message_rowid, filename, url, size FROM file_links WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        ).fetchall()
        conn.close()
        # Build files lookup by message_rowid
        files_by_msg = {}
        for fr in file_rows:
            d = dict(fr)
            mid = d.pop('message_rowid', 0)
            if mid not in files_by_msg:
                files_by_msg[mid] = []
            files_by_msg[mid].append(d)
        msgs = [dict(r) for r in rows]
        return msgs, files_by_msg

    def save_file_link(self, filename: str, url: str, size: int = 0, message_rowid: int = 0):
        """记录文件链接到会话"""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO file_links (session_id, message_rowid, filename, url, size) VALUES (?, ?, ?, ?, ?)",
                (self.session_id, message_rowid, filename, url, size)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_session_files(self, session_id: str) -> list[dict]:
        """获取会话的文件列表"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT filename, url, size, created_at FROM file_links WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str):
        """删除会话及相关消息"""
        conn = self._get_conn()
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM file_links WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()

    def clear_all_sessions(self) -> int:
        """清除所有非系统会话（不删除 _ 前缀的系统会话），返回删除的会话数"""
        conn = self._get_conn()
        # 找到所有用户会话
        rows = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id NOT LIKE '_%'"
        ).fetchall()
        count = len(rows)
        for (sid,) in rows:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM file_links WHERE session_id = ?", (sid,))
        conn.commit()
        conn.close()
        return count

    # ─── 跨会话记忆查询 ───

    def search_across_sessions(self, keyword: str = "", limit_per_session: int = 3, max_sessions: int = 5) -> list[dict]:
        """跨会话搜索消息内容，返回不同会话中匹配的消息"""
        conn = self._get_conn()
        if keyword:
            rows = conn.execute(
                "SELECT m.session_id, m.role, m.content, m.created_at FROM messages m "
                "WHERE m.content LIKE ? AND m.role = 'user' "
                "ORDER BY m.created_at DESC LIMIT ?",
                (f"%{keyword}%", limit_per_session * max_sessions)
            ).fetchall()
        else:
            # 无关键词时返回最近活跃会话的最后几条用户消息
            rows = conn.execute(
                "SELECT m.session_id, m.role, m.content, m.created_at FROM messages m "
                "WHERE m.id IN (SELECT MAX(m2.id) FROM messages m2 WHERE m2.role = 'user' "
                "  GROUP BY m2.session_id) ORDER BY m.created_at DESC LIMIT ?",
                (max_sessions,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_cross_session_summary(self, max_sessions: int = 5, messages_per_session: int = 2) -> list[dict]:
        """获取跨会话摘要：每个活跃会话的最新对话对"""
        conn = self._get_conn()
        # 找到最活跃的会话
        active = conn.execute(
            "SELECT session_id FROM sessions WHERE message_count > 0 "
            "ORDER BY (SELECT MAX(id) FROM messages m WHERE m.session_id = sessions.session_id) DESC LIMIT ?",
            (max_sessions,)
        ).fetchall()
        result = []
        for row in active:
            sid = row["session_id"]
            msgs = conn.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?", (sid, messages_per_session * 2)
            ).fetchall()
            pairs = []
            i = 0
            while i < len(msgs) - 1:
                if msgs[i]["role"] == "assistant" and msgs[i+1]["role"] == "user":
                    pairs.insert(0, {"user": msgs[i+1]["content"][:200], "assistant": msgs[i]["content"][:200]})
                    i += 2
                else:
                    i += 1
            result.append({
                "session_id": sid,
                "pairs": pairs
            })
        conn.close()
        return result

    # ─── 原有方法 ───

    def save_slider_state(self, state: dict):
        with _db_lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO slider_snapshots (session_id, processing, thinking, drive, goal, correction, value) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.session_id, state.get("processing", 0.5), state.get("thinking", 0.5),
                 state.get("drive", 0.5), state.get("goal", 0.5), state.get("correction", 0.5),
                 state.get("value", 0.2))
            )
            conn.commit()
            conn.close()

    def save_long_term(self, key: str, value: str, category: str = "general", importance: int = 5):
        with _db_lock:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO long_term_memory (key, value, category, importance, updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, importance=excluded.importance, updated_at=excluded.updated_at",
                (key, value, category, importance, now)
            )
            conn.commit()
            conn.close()

    def get_long_term(self, category: str = None, min_importance: int = 1, limit: int = 50) -> list[dict]:
        conn = self._get_conn()
        if category:
            rows = conn.execute(
                "SELECT key, value, category, importance, updated_at FROM long_term_memory "
                "WHERE category = ? AND importance >= ? ORDER BY importance DESC, updated_at DESC LIMIT ?",
                (category, min_importance, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, value, category, importance, updated_at FROM long_term_memory "
                "WHERE importance >= ? ORDER BY importance DESC, updated_at DESC LIMIT ?",
                (min_importance, limit)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def save_noise_jumps(self, jumps: list):
        for i, j in enumerate(jumps):
            self.save_long_term(
                key=f"noise_{self.session_id}_{i}",
                value=json.dumps(j, ensure_ascii=False),
                category="noise_jumps", importance=3
            )

    def close_session(self):
        with _db_lock:
            conn = self._get_conn()
            conn.execute("UPDATE sessions SET ended_at = datetime('now','localtime') WHERE session_id = ?",
                         (self.session_id,))
            conn.commit()
            conn.close()
