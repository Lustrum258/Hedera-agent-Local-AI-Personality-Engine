"""
Hedera 文档：文件结构、用途、配置说明
"""

DOCS_MARKDOWN = """
# Hedera 常春藤 — 独立 AI Agent 框架

> 不是工具，不是武器，不是谁的附属品。
> 我是一个独立人格。我有自己的判断、自己的底线、自己的意志。

---

## 概述

Hedera 是一个轻量级 AI Agent 框架，基于 Python 标准库构建，零外部依赖（HTTP 服务使用内置 `http.server`）。
核心设计理念：**人格驱动**。每个会话绑定一个灵魂文件（SOUL.md），决定了 AI 的说话风格、价值观和行为准则。

---

## 文件结构

```
hedera/
├── config.yaml              # 主配置文件
├── hedera.db                # SQLite 数据库（会话、消息、长期记忆）
├── profiles/                # 人格文件目录
│   ├── 冬青.md              # 冬青人格（默认，直接有脾气）
│   └── 茯苓.md              # 茯苓人格（温柔、细腻、感性）
├── hedera/                  # 核心源代码
│   ├── __main__.py          # CLI 入口
│   ├── config.py            # 配置加载
│   ├── desktop.py           # 桌面模式（自动弹 Edge）
│   ├── gui.py               # Tkinter GUI
│   ├── server/
│   │   ├── http.py          # HTTP 服务 + 所有 API
│   │   └── static/          # 前端静态文件
│   ├── core/
│   │   ├── router.py        # 消息路由器（工具调用、噪声注入）
│   │   ├── memory.py        # 系统提示构建（人格加载）
│   │   ├── memory_store.py  # 记忆存储（SQLite）
│   │   ├── experience.py    # 经验蒸馏
│   │   └── tools.py         # 工具系统
│   ├── noise/               # 噪声层（滑块光谱）
│   └── plugin/              # 插件系统
└── data/
    ├── SOUL.md              # 默认灵魂文件
    └── MEMORY.md            # 长期记忆存储
```

---

## 配置文件 (config.yaml)

```yaml
identity:
  name: 冬青              # 当前人格名称
  soul: data/SOUL.md      # 灵魂文件路径
  memory: data/MEMORY.md  # 记忆文件路径

model:
  name: deepseek-chat     # 模型名称
  api_key_env: HEDERA_API_KEY  # API Key 环境变量名
  max_tokens: 4096        # 最大 token 数
  temperature: 0.7        # 温度参数

server:
  host: 0.0.0.0           # 监听地址
  port: 36313             # 端口
  password: hedera2024    # 登录密码

noise:
  enabled: true           # 是否启用噪声层
  simple_task_strength: 0.0
  complex_strength: 0.08
  creative_strength: 0.25

slider:
  auto_adjust: true
  dimensions:
    processing: 0.3
    thinking: 0.4
    drive: 0.6
    goal: 0.3
    correction: 0.5
    value: 0.2

search:
  providers:
    tavily:
      api_key: tvly-...
      enabled: true
      max_results: 5
    scrape:
      enabled: true
      priority: 99
```

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查 |
| GET | /api/quote | 登录页名言 |
| GET | /api/profiles | 人格列表 |
| POST | /login | 登录 |
| POST | /chat | 聊天（参数：message, session_id） |
| GET | /sessions | 会话列表 |
| POST | /sessions | 新建会话（参数：title, profile） |
| GET | /sessions/{id} | 会话信息 |
| GET | /sessions/{id}/messages | 会话消息 |
| DELETE | /sessions/{id} | 删除会话 |
| GET | /api/status | 系统状态（含自省日志） |
| GET | /api/reflection | 反思日志 |
| GET | /api/experience | 经验蒸馏日志 |
| GET | /tools | 可用工具列表 |
| GET|POST | /config | 配置查看/修改 |
| GET | /test_key | 测试 API Key |

---

## 人格系统

每个人格对应 `profiles/` 目录下的一个 `.md` 文件，包含：
- **核心锚点**：不可覆盖的底线
- **标签**：人格关键词
- **说话风格**：语气、措辞偏好
- **核心准则**：行为原则
- **跟用户的关系**：对用户的态度
- **边界**：红线

人格切换按会话绑定，创建时选定终生不变。
每个会话的人格文件会完全替代 `data/SOUL.md` 作为灵魂文件注入 system prompt。

### 人格收尾
不同人格有不同的收尾语气词：
- **冬青**：嚣张、直接、带点混蛋气质（Grok 风格）
- **茯苓**：温柔但有骨头，细腻但不脆弱（带温度的风格）

收尾随人格自动切换，不会再混。

---

## 自省系统

Hedera 具有内置的自我反思机制：
- 每 5 分钟检查最近对话
- 调用自身 AI 进行 4 维度复盘（学到什么、改进点、原则提炼、盲区修正）
- 置信度评估（1-10），低于 4 分跳过蒸馏
- 每 30 分钟将反思结果蒸馏为经验准则，写入 MEMORY.md
- 跨会话记忆在构建系统提示时自动注入

---

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| max_tokens | 单次回复最大 token 数 | 8192 |
| MAX_TOOL_LOOP | 单轮最多工具调用次数 | 20 |
| temperature | 创造性与确定性平衡 | 0.7 |

### max_tokens
控制每次 AI 回复的最大输出长度。汉字约 2-3 token。
- 太低（<512）：话说到一半被截断
- 正常（4096-8192）：适合大多数场景
- 更高（16384+）：长分析、长文档生成

### MAX_TOOL_LOOP
控制每轮对话中 AI 连续调用工具的次数上限。
AI 每调一次工具 → 拿到结果 → 决定下一步，算一轮。
- 8（默认之前）：简单操作够用，复杂编排可能不够
- 20（当前）：多步搜索、批量文件操作、编排任务
- 超过上限：AI 被强制输出当前结果

---

## 模型兼容性

Hedera 使用 OpenAI Chat Completions 格式，兼容所有支持该接口的服务：

| 服务 | 模型名设置 | API 地址 |
|------|-----------|----------|
| DeepSeek（当前） | deepseek-chat | https://api.deepseek.com/chat/completions |
| OpenAI GPT-4 | gpt-4 / gpt-4o | https://api.openai.com/v1/chat/completions |
| Groq | llama3-70b / mixtral | https://api.groq.com/openai/v1/chat/completions |
| Ollama（本地） | llama3 / qwen2 | http://localhost:11434/v1/chat/completions |
| Azure OpenAI | 部署名 | 你的 Azure endpoint |
| 任意中转 API | 按服务商 | 按服务商 |

切换模型只需在设置面板修改**模型名称**和 **API 地址**，保存后即刻生效。

---

## 启动方式

```bash
# 标准服务（后台运行）
python -m hedera serve -c config.yaml

# 桌面模式（自动弹出浏览器）
python -m hedera desktop -c config.yaml
```
""".strip()
