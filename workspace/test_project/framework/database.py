"""Database ORM layer (simplified)"""
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Type, TypeVar
from dataclasses import dataclass, field, fields, asdict

T = TypeVar("T", bound="Model")

_db_lock = threading.local()


class QueryBuilder:
    def __init__(self, model_cls: Type["Model"], conn: sqlite3.Connection):
        self._model = model_cls
        self._conn = conn
        self._table = model_cls.__tablename__
        self._wheres: List[str] = []
        self._params: List[Any] = []
        self._order: str = ""
        self._limit_val: int = 0
        self._offset_val: int = 0
        self._select_cols: str = "*"
        self._joins: List[str] = []

    def where(self, condition: str, *params) -> "QueryBuilder":
        self._wheres.append(condition)
        self._params.extend(params)
        return self

    def order_by(self, column: str, desc: bool = False) -> "QueryBuilder":
        self._order = f"ORDER BY {column} {'DESC' if desc else 'ASC'}"
        return self

    def limit(self, n: int) -> "QueryBuilder":
        self._limit_val = n
        return self

    def offset(self, n: int) -> "QueryBuilder":
        self._offset_val = n
        return self

    def select(self, *cols: str) -> "QueryBuilder":
        self._select_cols = ", ".join(cols)
        return self

    def join(self, table: str, on: str) -> "QueryBuilder":
        self._joins.append(f"JOIN {table} ON {on}")
        return self

    def _build_sql(self) -> str:
        sql = f"SELECT {self._select_cols} FROM {self._table}"
        for j in self._joins:
            sql += f" {j}"
        if self._wheres:
            sql += " WHERE " + " AND ".join(self._wheres)
        if self._order:
            sql += f" {self._order}"
        if self._limit_val:
            sql += f" LIMIT {self._limit_val}"
        if self._offset_val:
            sql += f" OFFSET {self._offset_val}"
        return sql

    def all(self) -> List[Dict]:
        sql = self._build_sql()
        cursor = self._conn.execute(sql, self._params)
        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def first(self) -> Optional[Dict]:
        self._limit_val = 1
        results = self.all()
        return results[0] if results else None

    def count(self) -> int:
        self._select_cols = "COUNT(*) as cnt"
        result = self.first()
        return result["cnt"] if result else 0

    def delete(self) -> int:
        sql = f"DELETE FROM {self._table}"
        if self._wheres:
            sql += " WHERE " + " AND ".join(self._wheres)
        cursor = self._conn.execute(sql, self._params)
        self._conn.commit()
        return cursor.rowcount

    def update(self, **kwargs) -> int:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE {self._table} SET {sets}"
        params = list(kwargs.values())
        if self._wheres:
            sql += " WHERE " + " AND ".join(self._wheres)
            params.extend(self._params)
        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.rowcount


class Field:
    def __init__(self, col_type: str = "TEXT", primary_key: bool = False,
                 default: Any = None, nullable: bool = True, unique: bool = False):
        self.col_type = col_type
        self.primary_key = primary_key
        self.default = default
        self.nullable = nullable
        self.unique = unique


class Model:
    __tablename__: str = ""
    _db_path: str = ""

    def __init__(self, **kwargs):
        for f in fields(self.__class__):
            val = kwargs.get(f.name, f.default)
            setattr(self, f.name, val)

    @classmethod
    def _get_conn(cls) -> sqlite3.Connection:
        conn = sqlite3.connect(cls._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def create_table(cls):
        cols = []
        for f in fields(cls):
            parts = [f.name, "TEXT"]
            meta = f.metadata.get("field")
            if meta:
                parts[1] = meta.col_type
                if meta.primary_key:
                    parts.append("PRIMARY KEY AUTOINCREMENT")
                if not meta.nullable:
                    parts.append("NOT NULL")
                if meta.unique:
                    parts.append("UNIQUE")
                if meta.default is not None:
                    parts.append(f"DEFAULT '{meta.default}'")
            cols.append(" ".join(parts))
        sql = f"CREATE TABLE IF NOT EXISTS {cls.__tablename__} ({', '.join(cols)})"
        conn = cls._get_conn()
        conn.execute(sql)
        conn.commit()
        conn.close()

    def save(self) -> int:
        data = asdict(self)
        data.pop("id", None)
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {self.__tablename__} ({cols}) VALUES ({placeholders})"
        conn = self._get_conn()
        cursor = conn.execute(sql, list(data.values()))
        conn.commit()
        last_id = cursor.lastrowid
        conn.close()
        self.id = last_id
        return last_id

    @classmethod
    def query(cls) -> QueryBuilder:
        conn = cls._get_conn()
        return QueryBuilder(cls, conn)

    @classmethod
    def get_by_id(cls, id: int) -> Optional[Dict]:
        conn = cls._get_conn()
        result = conn.execute(f"SELECT * FROM {cls.__tablename__} WHERE id = ?", (id,)).fetchone()
        conn.close()
        return dict(result) if result else None

    @classmethod
    def delete_by_id(cls, id: int) -> bool:
        conn = cls._get_conn()
        cursor = conn.execute(f"DELETE FROM {cls.__tablename__} WHERE id = ?", (id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted
