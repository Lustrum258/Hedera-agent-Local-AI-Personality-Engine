"""
Hedera 加密存储模块
提供 API Key 和敏感信息的加密存储
"""

import os
import json
import base64
import hashlib
import secrets
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class CryptoError(Exception):
    """加密异常"""
    pass


class KeyDerivation:
    """密钥派生"""
    
    @staticmethod
    def derive_key(password: str, salt: bytes = None, iterations: int = 100000) -> Tuple[bytes, bytes]:
        """
        从密码派生密钥
        
        Args:
            password: 密码
            salt: 盐值（如果为None则自动生成）
            iterations: 迭代次数
            
        Returns:
            (密钥, 盐值)
        """
        if salt is None:
            salt = os.urandom(16)
        
        # 使用 PBKDF2 派生密钥
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key, salt
    
    @staticmethod
    def generate_machine_id() -> str:
        """
        生成机器唯一标识符
        
        Returns:
            机器ID字符串
        """
        # 收集系统信息
        info_parts = []
        
        # 主机名
        info_parts.append(os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "")))
        
        # 用户名
        info_parts.append(os.environ.get("USERNAME", os.environ.get("USER", "")))
        
        # 系统平台
        info_parts.append(os.sys.platform if hasattr(os, 'sys') else "")
        
        # 处理器信息
        info_parts.append(os.environ.get("PROCESSOR_IDENTIFIER", ""))
        
        # 组合并哈希
        combined = "|".join(info_parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:32]


class EncryptedStorage:
    """加密存储"""
    
    def __init__(self, storage_path: Optional[str] = None, password: Optional[str] = None):
        """
        初始化加密存储
        
        Args:
            storage_path: 存储文件路径
            password: 加密密码（如果为None则使用机器ID）
        """
        self.storage_path = storage_path or self._get_default_path()
        self.password = password or KeyDerivation.generate_machine_id()
        self._fernet: Optional[Fernet] = None
        self._salt: Optional[bytes] = None
        self._data: Dict[str, Any] = {}
        
        # 加载或初始化存储
        self._load_or_initialize()
    
    def _get_default_path(self) -> str:
        """获取默认存储路径"""
        # 使用用户目录下的 .hedera 目录
        home = Path.home()
        hedera_dir = home / ".hedera"
        hedera_dir.mkdir(exist_ok=True)
        return str(hedera_dir / "secure_storage.enc")
    
    def _load_or_initialize(self):
        """加载或初始化存储"""
        if os.path.exists(self.storage_path):
            self._load()
        else:
            self._initialize()
    
    def _initialize(self):
        """初始化新的存储"""
        # 生成盐值
        self._salt = os.urandom(16)
        
        # 派生密钥
        key, _ = KeyDerivation.derive_key(self.password, self._salt)
        self._fernet = Fernet(key)
        
        # 初始化空数据
        self._data = {}
        self._save()
    
    def _load(self):
        """加载加密存储"""
        try:
            with open(self.storage_path, "rb") as f:
                encrypted_data = f.read()
            
            # 读取盐值（前16字节）
            self._salt = encrypted_data[:16]
            encrypted_content = encrypted_data[16:]
            
            # 派生密钥
            key, _ = KeyDerivation.derive_key(self.password, self._salt)
            self._fernet = Fernet(key)
            
            # 解密数据
            decrypted = self._fernet.decrypt(encrypted_content)
            self._data = json.loads(decrypted.decode())
            
        except Exception as e:
            raise CryptoError(f"加载加密存储失败: {str(e)}")
    
    def _save(self):
        """保存加密存储"""
        try:
            # 序列化数据
            data_json = json.dumps(self._data, ensure_ascii=False)
            data_bytes = data_json.encode()
            
            # 加密数据
            encrypted = self._fernet.encrypt(data_bytes)
            
            # 保存到文件（盐值 + 加密数据）
            with open(self.storage_path, "wb") as f:
                f.write(self._salt + encrypted)
            
            # 设置文件权限（仅所有者可读写）
            try:
                os.chmod(self.storage_path, 0o600)
            except Exception:
                pass  # Windows 可能不支持
                
        except Exception as e:
            raise CryptoError(f"保存加密存储失败: {str(e)}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取加密存储的值
        
        Args:
            key: 键名
            default: 默认值
            
        Returns:
            存储的值
        """
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any):
        """
        设置加密存储的值
        
        Args:
            key: 键名
            value: 值
        """
        self._data[key] = value
        self._save()
    
    def delete(self, key: str) -> bool:
        """
        删除加密存储的值
        
        Args:
            key: 键名
            
        Returns:
            是否删除成功
        """
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False
    
    def keys(self) -> list:
        """获取所有键名"""
        return list(self._data.keys())
    
    def clear(self):
        """清空存储"""
        self._data = {}
        self._save()
    
    def export_encrypted(self) -> bytes:
        """导出加密数据（用于备份）"""
        with open(self.storage_path, "rb") as f:
            return f.read()
    
    def import_encrypted(self, encrypted_data: bytes):
        """导入加密数据（用于恢复）"""
        with open(self.storage_path, "wb") as f:
            f.write(encrypted_data)
        self._load()


class APIKeyManager:
    """API Key 管理器"""
    
    def __init__(self, storage: Optional[EncryptedStorage] = None):
        """
        初始化 API Key 管理器
        
        Args:
            storage: 加密存储实例
        """
        self.storage = storage or EncryptedStorage()
        self._key_prefix = "api_key_"
    
    def set_api_key(self, service: str, key: str, metadata: Optional[Dict] = None):
        """
        设置 API Key
        
        Args:
            service: 服务名称（如 openai, deepseek, tavily）
            key: API Key
            metadata: 元数据（如过期时间、权限等）
        """
        storage_key = f"{self._key_prefix}{service}"
        value = {
            "key": key,
            "created_at": self._get_timestamp(),
            "metadata": metadata or {},
        }
        self.storage.set(storage_key, value)
    
    def get_api_key(self, service: str) -> Optional[str]:
        """
        获取 API Key
        
        Args:
            service: 服务名称
            
        Returns:
            API Key 或 None
        """
        storage_key = f"{self._key_prefix}{service}"
        value = self.storage.get(storage_key)
        if value and isinstance(value, dict):
            return value.get("key")
        return None
    
    def get_api_key_with_metadata(self, service: str) -> Optional[Dict]:
        """
        获取 API Key 及其元数据
        
        Args:
            service: 服务名称
            
        Returns:
            包含 key 和 metadata 的字典
        """
        storage_key = f"{self._key_prefix}{service}"
        return self.storage.get(storage_key)
    
    def delete_api_key(self, service: str) -> bool:
        """
        删除 API Key
        
        Args:
            service: 服务名称
            
        Returns:
            是否删除成功
        """
        storage_key = f"{self._key_prefix}{service}"
        return self.storage.delete(storage_key)
    
    def list_services(self) -> list:
        """列出所有已存储的服务"""
        services = []
        for key in self.storage.keys():
            if key.startswith(self._key_prefix):
                service = key[len(self._key_prefix):]
                services.append(service)
        return services
    
    def rotate_key(self, service: str, new_key: str):
        """
        轮换 API Key
        
        Args:
            service: 服务名称
            new_key: 新的 API Key
        """
        # 获取现有元数据
        existing = self.get_api_key_with_metadata(service)
        metadata = existing.get("metadata", {}) if existing else {}
        
        # 保存旧密钥信息
        if "previous_keys" not in metadata:
            metadata["previous_keys"] = []
        
        if existing and existing.get("key"):
            metadata["previous_keys"].append({
                "key": existing["key"],
                "rotated_at": self._get_timestamp(),
            })
            
            # 只保留最近3个旧密钥
            metadata["previous_keys"] = metadata["previous_keys"][-3:]
        
        # 设置新密钥
        self.set_api_key(service, new_key, metadata)
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


# 全局实例
_api_key_manager: Optional[APIKeyManager] = None
_encrypted_storage: Optional[EncryptedStorage] = None


def get_encrypted_storage() -> EncryptedStorage:
    """获取全局加密存储实例"""
    global _encrypted_storage
    if _encrypted_storage is None:
        _encrypted_storage = EncryptedStorage()
    return _encrypted_storage


def get_api_key_manager() -> APIKeyManager:
    """获取全局 API Key 管理器实例"""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = APIKeyManager(get_encrypted_storage())
    return _api_key_manager


def migrate_plaintext_keys(config_path: str) -> Dict[str, Any]:
    """
    迁移明文 API Key 到加密存储
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        迁移结果
    """
    results = {
        "migrated": [],
        "skipped": [],
        "errors": [],
    }
    
    try:
        # 读取配置文件
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        if not config:
            return results
        
        # 获取 API Key 管理器
        manager = get_api_key_manager()
        
        # 遍历配置查找 API Key
        def find_and_migrate(data, path=""):
            if isinstance(data, dict):
                for key, value in data.items():
                    current_path = f"{path}.{key}" if path else key
                    
                    # 检查是否是 API Key
                    if key in ("api_key", "api_key_env", "key"):
                        if isinstance(value, str) and value and not value.startswith("$"):
                            # 这是一个明文 API Key
                            service = path.split(".")[-1] if path else "unknown"
                            
                            try:
                                manager.set_api_key(service, value, {
                                    "source": config_path,
                                    "path": current_path,
                                })
                                results["migrated"].append({
                                    "service": service,
                                    "path": current_path,
                                })
                            except Exception as e:
                                results["errors"].append({
                                    "path": current_path,
                                    "error": str(e),
                                })
                        else:
                            results["skipped"].append({
                                "path": current_path,
                                "reason": "环境变量引用或空值",
                            })
                    
                    # 递归处理嵌套字典
                    find_and_migrate(value, current_path)
            
            elif isinstance(data, list):
                for i, item in enumerate(data):
                    find_and_migrate(item, f"{path}[{i}]")
        
        find_and_migrate(config)
        
    except Exception as e:
        results["errors"].append({
            "path": "config",
            "error": str(e),
        })
    
    return results


# 测试函数
if __name__ == "__main__":
    # 测试加密存储
    storage = EncryptedStorage("test_storage.enc", "test_password")
    
    # 测试存储
    storage.set("test_key", "test_value")
    print(f"存储的值: {storage.get('test_key')}")
    
    # 测试 API Key 管理器
    manager = APIKeyManager(storage)
    manager.set_api_key("openai", "sk-test-key-12345")
    print(f"OpenAI Key: {manager.get_api_key('openai')}")
    print(f"所有服务: {manager.list_services()}")
    
    # 清理测试文件
    import os
    os.unlink("test_storage.enc")
    print("测试完成")