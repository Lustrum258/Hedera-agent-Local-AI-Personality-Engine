"""Config loader with environment variable support"""
import os
import json
from typing import Any, Dict, Optional


class Config:
    """Configuration manager with env var override support"""
    
    _defaults: Dict[str, Any] = {
        "app_name": "Hedera Test App",
        "debug": False,
        "host": "0.0.0.0",
        "port": 8000,
        "secret_key": "change-me-in-production",
        "database": {
            "url": "sqlite:///app.db",
            "pool_size": 5,
            "echo": False,
        },
        "auth": {
            "token_expire_seconds": 3600,
            "max_login_attempts": 5,
            "lockout_minutes": 15,
        },
        "cors": {
            "enabled": True,
            "origins": ["http://localhost:3000"],
            "methods": ["GET", "POST", "PUT", "DELETE"],
        },
        "logging": {
            "level": "INFO",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        "cache": {
            "enabled": True,
            "ttl": 300,
            "max_size": 1000,
        },
    }

    def __init__(self, config_file: Optional[str] = None, env_prefix: str = "APP"):
        self._data = {}
        self._env_prefix = env_prefix
        
        # Load defaults
        self._data = self._deep_copy(self._defaults)
        
        # Load from file
        if config_file and os.path.exists(config_file):
            with open(config_file, "r") as f:
                file_config = json.load(f)
            self._data = self._deep_merge(self._data, file_config)
        
        # Override with env vars
        self._load_env_vars()

    def _deep_copy(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._deep_copy(item) for item in obj]
        return obj

    def _deep_merge(self, base: dict, override: dict) -> dict:
        result = self._deep_copy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = self._deep_copy(value)
        return result

    def _load_env_vars(self):
        prefix = f"{self._env_prefix}_"
        for key, value in os.environ.items():
            if key.startswith(prefix):
                parts = key[len(prefix):].lower().split("_")
                self._set_nested(self._data, parts, self._parse_value(value))

    def _set_nested(self, data: dict, parts: list, value: Any):
        if len(parts) == 1:
            data[parts[0]] = value
        else:
            if parts[0] not in data:
                data[parts[0]] = {}
            self._set_nested(data[parts[0]], parts[1:], value)

    def _parse_value(self, value: str) -> Any:
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value

    def get(self, key: str, default: Any = None) -> Any:
        parts = key.split(".")
        data = self._data
        for part in parts:
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                return default
        return data

    def set(self, key: str, value: Any):
        parts = key.split(".")
        data = self._data
        for part in parts[:-1]:
            if part not in data:
                data[part] = {}
            data = data[part]
        data[parts[-1]] = value

    def to_dict(self) -> dict:
        return self._deep_copy(self._data)
