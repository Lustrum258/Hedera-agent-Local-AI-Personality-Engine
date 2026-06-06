import httpx
import json

# 测试Hedera连接
HEDERA_URL = "http://localhost:36313/webhook"

async def test_connection():
    """测试与Hedera的连接"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("http://localhost:36313/")
            print(f"✓ Hedera服务器连接成功，状态码: {response.status_code}")
            return True
    except Exception as e:
        print(f"✗ 无法连接到Hedera服务器: {e}")
        return False

async def test_webhook():
    """测试webhook接口"""
    test_message = "你好，这是测试消息"
    payload = {"message": test_message}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(HEDERA_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if "response" in data:
                print(f"✓ Webhook测试成功")
                print(f"  发送: {test_message}")
                print(f"  收到: {data['response'][:100]}...")
                return True
            else:
                print(f"✗ Webhook返回异常: {data}")
                return False
                
    except Exception as e:
        print(f"✗ Webhook测试失败: {e}")
        return False

async def main():
    print("测试Hedera连接...")
    
    if await test_connection():
        print("\n测试Webhook接口...")
        await test_webhook()
    else:
        print("\n请确保Hedera服务器正在运行。")
        print("启动命令: cd hedera && python -m hedera.server.http")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())