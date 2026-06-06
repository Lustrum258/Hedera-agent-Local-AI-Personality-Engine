# Hedera QQ Bot

这是一个将QQ消息转发到Hedera AI的QQ机器人，基于NoneBot2框架。

## 前置要求

1. **Hedera服务器运行中** - 默认在 `http://localhost:36313`
2. **QQ协议端** - 推荐使用以下之一：
   - [NapCat](https://github.com/NapNeko/NapCatQQ) - 基于NTQQ的协议端
   - [LLOneBot](https://github.com/LLOneBot/LLOneBot) - 另一种OneBot实现

## 安装步骤

### 1. 安装QQ协议端

#### NapCat（推荐）
1. 下载NapCat：https://github.com/NapNeko/NapCatQQ/releases
2. 配置NapCat：
   - 下载后解压，运行 `napcat.bat`
   - 登录你的QQ账号
   - 在配置中启用WebSocket服务器，默认端口6700

#### LLOneBot
1. 下载LLOneBot：https://github.com/LLOneBot/LLOneBot/releases
2. 安装到QQ的plugins目录
3. 启动QQ后启用插件，配置WebSocket服务器

### 2. 配置机器人

编辑 `.env` 文件：

```env
# OneBot WebSocket连接地址
ONEBOT_WS_URLS=["ws://127.0.0.1:6700"]

# 如果设置了access_token，在这里填写
ONEBOT_ACCESS_TOKEN=your_token_here

# 机器人监听端口
PORT=8080
```

### 3. 启动机器人

```bash
# 确保Hedera服务器在运行
cd hedera
python -m hedera.server.http

# 在另一个终端启动QQ机器人
cd qq_bot
python bot.py
```

或者直接运行 `start_bot.bat`

## 使用说明

1. 将机器人QQ号加入群聊或直接私聊
2. 发送任何消息给机器人
3. 机器人会转发到Hedera处理并返回回复

## 工作原理

```
QQ用户 → QQ协议端(NapCat/LLOneBot) → NoneBot2 → Hedera Webhook → 回复
```

## 故障排除

### 1. 机器人不回复
- 检查NapCat/LLOneBot是否运行
- 检查Hedera服务器是否运行在36313端口
- 查看NoneBot2控制台是否有错误信息

### 2. 连接失败
- 确认`.env`中的WebSocket地址正确
- 确认QQ协议端已启动WebSocket服务器

### 3. 回复很慢
- 这是正常的，Hedera需要时间生成回复
- 复杂问题可能需要更长时间

## 进阶配置

### 修改Hedera地址
如果Hedera运行在不同地址，修改 `plugins/hedera_bridge.py` 中的：
```python
HEDERA_WEBHOOK_URL = "http://your-hedera-address:port/webhook"
```

### 添加命令
可以在插件中添加命令处理，比如 `/clear` 清除会话历史。

### 多群管理
机器人默认对所有消息响应。如果需要限制，可以添加群组白名单。

## 注意事项

1. **QQ风险**：使用第三方协议端可能有封号风险，建议使用小号
2. **频率限制**：避免短时间内发送大量消息
3. **隐私**：所有消息都会经过Hedera处理，注意隐私安全

## 开发说明

项目结构：
```
qq_bot/
├── bot.py              # NoneBot2主程序
├── plugins/
│   └── hedera_bridge.py # Hedera桥接插件
├── .env                # 配置文件
└── pyproject.toml      # 项目依赖
```