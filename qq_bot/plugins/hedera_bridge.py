import httpx
from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent, Message
from nonebot.params import CommandArg
from nonebot.typing import T_State

# Hedera webhook地址
HEDERA_WEBHOOK_URL = "http://localhost:36313/webhook"

# 用于存储用户会话ID的映射
user_sessions = {}

# 匹配所有消息
matcher = on_message(priority=5, block=True)

@matcher.handle()
async def handle_message(event: GroupMessageEvent | PrivateMessageEvent, state: T_State):
    # 获取用户消息
    user_message = event.get_plaintext().strip()
    if not user_message:
        return  # 忽略空消息
    
    # 获取用户ID作为session_id
    user_id = str(event.user_id)
    session_id = user_sessions.get(user_id)
    
    # 构建请求数据
    payload = {
        "message": user_message,
        "session_id": session_id
    }
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(HEDERA_WEBHOOK_URL, json=payload)
            response.raise_for_status()
            data = response.json()
            
            if "response" in data:
                # 同步回复
                reply = data["response"]
                # 保存session_id供后续使用
                if "session_id" in data:
                    user_sessions[user_id] = data["session_id"]
                
                # 发送回复
                await matcher.finish(reply)
            elif "error" in data:
                await matcher.finish(f"处理出错: {data['error']}")
            else:
                await matcher.finish("收到消息但未能生成回复")
                
    except httpx.TimeoutException:
        await matcher.finish("处理超时，请稍后再试")
    except httpx.HTTPStatusError as e:
        await matcher.finish(f"HTTP错误: {e.response.status_code}")
    except Exception as e:
        await matcher.finish(f"发生错误: {str(e)}")