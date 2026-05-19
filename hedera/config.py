"""
Hedera 配置系统
从 yaml 文件加载配置，合并默认值。
支持热加载：改 config.yaml 后自动检测，无需重启。
"""

import os
import yaml
import time
import threading
from typing import Any

_DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default.yaml")
_GLOBAL_SECTION = "__hedera__"


class ConfigManager:
    """
    配置管理器，支持热加载。
    使用时调用 .get() 获取当前配置，后台自动检测文件变更。

   用法：
       cm = ConfigManager("config.yaml")
       cfg = cm.get()              # 自动检查是否需重载
       cm.reload()                 # 手动重载
       cm.force_reload()           # 强制重载（忽略 mtime）
    """

    def __init__(self, path: str | None = None):
        self._path = os.path.abspath(path) if path else None
        self._lock = threading.Lock()
        self._config: dict = {}
        self._last_mtime: float = 0
        self._reload_count: int = 0
        self._last_load_error: str = ""
        self._load()

    def get(self) -> dict:
        """获取当前配置。自动检测文件变更，dirty 则静默重载。"""
        if self._is_dirty():
            try:
                self._load()
            except Exception:
                pass  # 重载失败用旧配置继续
        return self._config

    def reload(self) -> dict:
        """手动重载配置。检测 mtime，有变更才重载。"""
        if self._is_dirty():
            self._load()
        return self._config

    def force_reload(self) -> dict:
        """强制重载，忽略 mtime。"""
        self._load()
        return self._config

    @property
    def path(self) -> str | None:
        return self._path

    @path.setter
    def path(self, new_path: str | None):
        self._path = os.path.abspath(new_path) if new_path else None
        self.force_reload()

    @property
    def stats(self) -> dict:
        return {
            "path": self._path,
            "reload_count": self._reload_count,
            "last_load_error": self._last_load_error,
            "last_mtime": self._last_mtime,
            "size": len(str(self._config)),
        }

    def _is_dirty(self) -> bool:
        if not self._path or not os.path.exists(self._path):
            return False
        try:
            current_mtime = os.path.getmtime(self._path)
            return current_mtime > self._last_mtime
        except Exception:
            return False

    def _load(self):
        with self._lock:
            try:
                defaults = _load_yaml(_DEFAULT_CONFIG_PATH) or {}
                if self._path and os.path.exists(self._path):
                    user_cfg = _load_yaml(self._path) or {}
                    merged = _deep_merge(defaults, user_cfg)
                else:
                    merged = dict(defaults)

                if self._path:
                    merged[_GLOBAL_SECTION] = {"config_dir": os.path.dirname(self._path)}
                    self._last_mtime = os.path.getmtime(self._path)
                else:
                    merged[_GLOBAL_SECTION] = {"config_dir": os.getcwd()}

                self._config = merged
                self._reload_count += 1
                self._last_load_error = ""
            except Exception as e:
                self._last_load_error = str(e)
                if not self._config:
                    # 首次加载就炸了 → 给个空配置兜底
                    self._config = {_GLOBAL_SECTION: {"config_dir": os.getcwd()}}


# 默认加载函数（兼容旧代码，直接返回原始 dict）
def load_config(path: str = None) -> dict:
    defaults = _load_yaml(_DEFAULT_CONFIG_PATH) or {}
    if path and os.path.exists(path):
        user_cfg = _load_yaml(path) or {}
        merged = _deep_merge(defaults, user_cfg)
    else:
        merged = dict(defaults)
    if path:
        merged[_GLOBAL_SECTION] = {"config_dir": os.path.dirname(os.path.abspath(path))}
    else:
        merged[_GLOBAL_SECTION] = {"config_dir": os.getcwd()}
    return merged


def get_data_dir(config: dict) -> str:
    cfg_dir = config.get(_GLOBAL_SECTION, {}).get("config_dir", os.getcwd())
    data_dir = config.get("paths", {}).get("data_dir", "")
    if data_dir:
        if os.path.isabs(data_dir):
            return data_dir
        return os.path.join(cfg_dir, data_dir)
    return os.path.join(cfg_dir, "data")


def _load_yaml(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def get_model_config(config: dict) -> dict:
    return config.get("model", {})


def get_search_config(config: dict) -> dict:
    return config.get("search", {})
