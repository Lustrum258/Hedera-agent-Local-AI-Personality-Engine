# NapCat 配置指南

## 快速开始

### 第一步：下载NapCat

1. 访问 https://github.com/NapNeko/NapCatQQ/releases
2. 下载 `NapCat.Shell.zip`（Windows版本）
3. 解压到 `qq_bot/NapCat` 目录

```
qq_bot/
├── NapCat/
│   ├── launcher.bat
│   ├── napcat.bat
│   └── ...
├── bot.py
└── start_bot.bat
```

### 第二步：启动NapCat

运行 `start_napcat.bat` 或直接运行 `NapCat/launcher.bat`

首次启动会显示二维码，用手机QQ扫码登录。

### 第三步：配置WebSocket服务器

1. 登录后访问 http://localhost:6099 进入WebUI
2. 点击左侧 **"网络配置"**
3. 点击 **"添加"** -> **"WebSocket服务器"**
4. 配置如下：
   - 名称：`ws-server`（可自定义）
   - 启用：✅
   - 主机地址：`0.0.0.0`
   - 端口：`6700`
   - 消息格式：`数组`（array）
   - Access Token：留空（或自定义）
5. 点击 **"保存"**

### 第四步：启动NoneBot2

运行 `start_bot.bat` 或执行：
```bash
cd qq_bot
python bot.py
```

## 验证连接

运行测试脚本：
```bash
python test_connection.py
```

## 常见问题

### Q: 扫码后显示"登录失败"
A: 尝试以下方法：
- 使用QQ 9.9.12-27556版本
- 清除NapCat的data目录后重试
- 使用其他QQ号

### Q: NoneBot2连接不上NapCat
A: 检查：
- NapCat是否已登录
- WebSocket服务器是否启动（端口6700）
- 防火墙是否放行6700端口

### Q: 机器人在群里不回复
A: 可能原因：
- 群聊中需要@机器人
- NapCat未启用"群聊"权限
- 检查NapCat日志是否有报错

### Q: NapCat启动后没有二维码
A: 
- 检查是否安装了QQ
- 尝试以管理员权限运行
- 查看NapCat目录下的日志文件

## NapCat WebUI 配置详解

### 网络配置

| 配置项 | 说明 | 建议值 |
|--------|------|--------|
| 主机地址 | 监听地址 | `0.0.0.0` |
| 端口 | WebSocket端口 | `6700` |
| 消息格式 | 上报格式 | `array` |
| Token | 认证令牌 | 留空 |

### 权限配置

在"群聊配置"中可以设置：
- 群聊回复权限
- 私聊回复权限
- 管理员命令权限

## 备用方案：使用LLOneBot

如果NapCat无法使用，可以尝试LLOneBot：

1. 下载：https://github.com/LLOneBot/LLOneBot/releases
2. 安装到QQ的plugins目录
3. 启动QQ后在设置中启用LLOneBot
4. 配置WebSocket服务器（端口6700）

## 技术架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   QQ用户    │────>│  NapCat/LLOneBot │────>│  NoneBot2   │
│             │<────│  (端口6700)   │<────│  (端口8080)  │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                                              │ HTTP
                                              ▼
                                        ┌─────────────┐
                                        │   Hedera    │
                                        │  (端口36313) │
                                        └─────────────┘
```