"""
Hedera 初始化模块
负责在启动时初始化加密存储、沙箱等安全组件
"""

import os
import sys
from pathlib import Path


def init_security(data_dir: str = None):
    """
    初始化安全组件
    
    Args:
        data_dir: 数据目录路径
    """
    print("[Hedera] 初始化安全组件...")
    
    # 1. 初始化加密存储
    _init_crypto_storage(data_dir)
    
    # 2. 初始化沙箱
    _init_sandbox()
    
    # 3. 检查是否需要迁移 API Key
    _check_migration_needed()
    
    print("[Hedera] 安全组件初始化完成")


def _init_crypto_storage(data_dir: str = None):
    """初始化加密存储"""
    try:
        from hedera.core.crypto import get_encrypted_storage, get_api_key_manager
        
        # 确保存储目录存在
        if data_dir:
            storage_dir = os.path.join(data_dir, ".secure")
            os.makedirs(storage_dir, exist_ok=True)
        
        # 初始化存储
        storage = get_encrypted_storage()
        manager = get_api_key_manager()
        
        # 检查是否有已存储的密钥
        services = manager.list_services()
        if services:
            print(f"[Hedera] 加密存储已加载，包含 {len(services)} 个服务的 API Key")
        else:
            print("[Hedera] 加密存储已初始化（空）")
            
    except Exception as e:
        print(f"[Hedera] 加密存储初始化失败: {str(e)}")


def _init_sandbox():
    """初始化沙箱"""
    try:
        from hedera.core.sandbox import get_python_sandbox, get_shell_sandbox
        
        # 预热沙箱实例
        get_python_sandbox()
        get_shell_sandbox()
        
        print("[Hedera] 沙箱隔离已启用")
    except Exception as e:
        print(f"[Hedera] 沙箱初始化失败: {str(e)}")


def _check_migration_needed():
    """检查是否需要迁移 API Key"""
    try:
        # 检查配置文件中是否有明文 API Key
        config_path = os.path.join(os.getcwd(), "config.yaml")
        if not os.path.exists(config_path):
            return
        
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        if not config:
            return
        
        # 查找明文 API Key
        has_plaintext_keys = False
        
        def check_keys(data):
            nonlocal has_plaintext_keys
            if isinstance(data, dict):
                for key, value in data.items():
                    if key == "api_key" and isinstance(value, str) and value and not value.startswith("$") and not value.startswith("@encrypted:"):
                        has_plaintext_keys = True
                        return
                    check_keys(value)
            elif isinstance(data, list):
                for item in data:
                    check_keys(item)
        
        check_keys(config)
        
        if has_plaintext_keys:
            print("[Hedera] 检测到配置文件中存在明文 API Key")
            print("[Hedera] 建议运行 'python migrate_keys.py' 迁移到加密存储")
            
    except Exception:
        pass


def cleanup_security():
    """清理安全组件"""
    try:
        from hedera.core.sandbox import cleanup_sandboxes
        cleanup_sandboxes()
        print("[Hedera] 沙箱资源已清理")
    except Exception:
        pass


# 自动初始化（当模块被导入时）
if __name__ != "__main__":
    # 延迟初始化，避免循环导入
    _initialized = False
    
    def auto_init():
        global _initialized
        if not _initialized:
            try:
                init_security()
                _initialized = True
            except Exception:
                pass
    
    # 不自动初始化，由主程序显式调用
    # auto_init()