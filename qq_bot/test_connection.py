"""
测试NapCat和Hedera连接状态
运行: python test_connection.py
"""

import socket
import httpx
import asyncio
import sys

def check_port(host, port, name):
    """检查端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            print(f"[OK] {name} 端口 {port} 已开放")
            return True
        else:
            print(f"[FAIL] {name} 端口 {port} 未开放")
            return False
    except Exception as e:
        print(f"[FAIL] {name} 检查失败: {e}")
        return False

async def check_hedera():
    """检查Hedera服务状态"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:36313/")
            print(f"[OK] Hedera HTTP服务正常 (状态码: {response.status_code})")
            return True
    except Exception as e:
        print(f"[FAIL] Hedera HTTP服务异常: {e}")
        return False

async def check_nonebot():
    """检查NoneBot2服务状态"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("http://localhost:8080/")
            print(f"[OK] NoneBot2 HTTP服务正常 (状态码: {response.status_code})")
            return True
    except Exception as e:
        print(f"[WARN] NoneBot2 HTTP服务未启动（这是正常的，NoneBot2主要使用WebSocket）")
        return True  # NoneBot2主要使用WebSocket，HTTP不一定要开放

async def main():
    print("=" * 50)
    print("  QQ机器人连接状态检测")
    print("=" * 50)
    print()
    
    results = []
    
    # 检查NapCat WebSocket端口
    print("[1] 检查NapCat (端口6700)...")
    napcat_ok = check_port("127.0.0.1", 6700, "NapCat WebSocket")
    results.append(("NapCat", napcat_ok))
    
    # 检查NoneBot2端口
    print("\n[2] 检查NoneBot2 (端口8080)...")
    nonebot_ok = check_port("127.0.0.1", 8080, "NoneBot2 HTTP")
    results.append(("NoneBot2", nonebot_ok))
    
    # 检查Hedera端口
    print("\n[3] 检查Hedera (端口36313)...")
    hedera_ok = check_port("127.0.0.1", 36313, "Hedera HTTP")
    results.append(("Hedera", hedera_ok))
    
    # 检查Hedera HTTP服务
    if hedera_ok:
        print("\n[4] 测试Hedera HTTP连接...")
        hedera_http_ok = await check_hedera()
        results.append(("Hedera HTTP", hedera_http_ok))
    
    # 汇总结果
    print("\n" + "=" * 50)
    print("  检测结果汇总")
    print("=" * 50)
    
    all_ok = True
    for name, ok in results:
        status = "[OK] 正常" if ok else "[FAIL] 异常"
        print(f"  {name}: {status}")
        if not ok:
            all_ok = False
    
    print("\n" + "=" * 50)
    
    if all_ok:
        print("[OK] 所有服务运行正常！")
        print("\n你现在可以:")
        print("1. 启动NoneBot2: python bot.py")
        print("2. 在QQ上给机器人发消息测试")
    else:
        print("[WARN] 部分服务未启动，请按以下顺序启动:")
        print()
        if not napcat_ok:
            print("1. 启动NapCat: 运行 start_napcat.bat")
            print("   - 扫码登录QQ")
            print("   - 配置WebSocket服务器 (端口6700)")
            print()
        if not hedera_ok:
            print("2. 启动Hedera: cd ../hedera && python -m hedera.server.http")
            print()
        if not nonebot_ok:
            print("3. 启动NoneBot2: python bot.py")
    
    print()
    input("按Enter键退出...")

if __name__ == "__main__":
    asyncio.run(main())