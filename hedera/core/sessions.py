"""
Hedera 会话管理
"""

import os

from hedera.core.memory_store import MemoryStore


class SessionManager:
    """封装所有会话存储状态与操作"""

    def __init__(self):
        self._session_stores: dict[str, MemoryStore] = {}
        self._session_db_dir = None
        self._store = None

    def ensure_store(self, config: dict, session_id: str = None) -> MemoryStore:
        """
        获取或创建指定会话的 MemoryStore。
        如果 session_id 为 None，使用默认的全局会话。
        """
        data_dir = config.get("__hedera__", {}).get("config_dir", os.getcwd())
        identity_cfg = config.get("identity", {})
        mem_path = identity_cfg.get("memory", "data/MEMORY.md")
        if not os.path.isabs(mem_path):
            mem_path = os.path.join(data_dir, os.path.dirname(mem_path))
        db_dir = os.path.dirname(os.path.abspath(mem_path))
        # 修复：如果 db_dir 结尾不是 data（被 os.path.dirname 吃掉了一层），补上
        need_data_dir = os.path.join(data_dir, "data")
        if os.path.dirname(os.path.abspath(mem_path)) == data_dir and os.path.isdir(need_data_dir):
            db_dir = need_data_dir
        self._session_db_dir = db_dir

        # 没有 session_id → 使用固定默认会话（跨重启稳定）
        if session_id is None:
            if self._store is None:
                self._store = MemoryStore(db_dir, session_id="_default")
            return self._store

        # 显式 session_id → 多会话模式
        if session_id not in self._session_stores:
            self._session_stores[session_id] = MemoryStore(db_dir, session_id=session_id)
        return self._session_stores[session_id]

    def list_sessions(self) -> list[dict]:
        """列出所有会话"""
        self.ensure_store(config={}, session_id="_admin")
        if self._session_db_dir:
            q = MemoryStore(self._session_db_dir, session_id="_admin")
            return q.list_sessions()
        return []

    def create_session(self, session_id: str = None, title: str = "") -> dict:
        """创建新会话"""
        if not self._session_db_dir:
            return {"error": "no db dir"}
        q = MemoryStore(self._session_db_dir, session_id="_admin")
        sid = q.create_session(session_id, title)
        return {"session_id": sid, "title": title}

    def get_session_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        """获取指定会话的消息"""
        if not self._session_db_dir:
            return []
        q = MemoryStore(self._session_db_dir, session_id="_admin")
        return q.get_session_messages(session_id, limit)

    def delete_session(self, session_id: str) -> dict:
        """删除会话"""
        if not self._session_db_dir:
            return {"error": "no db dir"}
        q = MemoryStore(self._session_db_dir, session_id="_admin")
        q.delete_session(session_id)
        # 清理缓存
        if session_id in self._session_stores:
            del self._session_stores[session_id]
        return {"status": "deleted", "session_id": session_id}

    def clear_all_sessions_cache(self):
        """清除所有会话的内存缓存（配合 clear_all_sessions 使用）"""
        self._session_stores.clear()

    def reset(self):
        """Full reset of all session state (used by router.reset_state)"""
        self._session_stores.clear()
        self._session_db_dir = None
        self._store = None


# 模块级单例，供 router.py 和外部直接调用
_session_manager = SessionManager()

ensure_store = _session_manager.ensure_store
list_sessions = _session_manager.list_sessions
create_session = _session_manager.create_session
get_session_messages = _session_manager.get_session_messages
delete_session = _session_manager.delete_session
clear_all_sessions_cache = _session_manager.clear_all_sessions_cache
