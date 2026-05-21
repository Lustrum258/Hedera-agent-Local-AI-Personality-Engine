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

## 特性

- **人格切换** — 通过 SOUL.md 定义人格，创建会话时选择，终生绑定
- **独立会话** — 每个会话有自己的历史、人格、记忆，互不干扰
- **跨会话记忆** — 自动注入其他会话的关键上下文和经验准则
- **自省系统** — 定期复盘对话，提炼经验准则，发现认知盲区
- **噪声层** — 让输出不千篇一律，同一问题不同角度
- **滑块光谱** — 6 维度动态调节 Agent 性格状态
- **图像生成** — 通过 generate_image 工具调用，支持 OpenAI 兼容 API
- **实时工具进度** — 前端实时显示工具调用链（流式 ndjson + 轮询双通道）
- **自提问机制** — 模拟好奇心，连续 3 次无回答自动闭嘴
- **零依赖 HTTP 服务** — 使用 Python 内置 http.server，无需安装框架
- **多模型支持** — 兼容 OpenAI Chat Completions 格式
- **纯 HTML 管理界面** — 会话管理、人格切换、设置、自省监控、文档
- **插件系统** — 可扩展的工具插件架构

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
│   │   └── tools.py         # 工具系统（含图像生成）
│   ├── noise/               # 噪声层（滑块光谱）
│   ├── training/            # 训练协议（自提问脉冲）
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
  max_tokens: 8192        # 最大 token 数
  temperature: 0.7        # 温度参数

server:
  host: 0.0.0.0           # 监听地址
  port: 36313             # 端口
  password: hedera2024    # 登录密码

image_gen:                 # 图像生成（可选）
  enabled: true
  api_key_env: HEDERA_IMAGE_KEY
  api_key: ""              # 直接填 Key
  model: dall-e-3
  endpoint: ""             # 空 = 自动推导
  size: 1024x1024
  quality: standard
  n: 1

noise:
  enabled: true
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

training:                  # 训练协议
  enabled: true
  module_a: true
  module_c: true
  module_d: true
  pulse_interval: 300
```

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查 |
| GET | /api/quote | 登录页名言 |
| GET | /api/profiles | 人格列表 |
| POST | /login | 登录 |
| POST | /chat | **聊天**（返回 ndjson 流）|
| GET | /chat/progress | 轮询工具调用进度 |
| GET | /sessions | 会话列表 |
| POST | /sessions | 新建会话（参数：title, profile） |
| GET | /sessions/{id} | 会话信息 |
| GET | /sessions/{id}/messages | 会话消息 |
| DELETE | /sessions/{id} | 删除会话 |
| POST | /sessions/clear_all | 清除所有会话 |
| GET | /api/status | 系统状态（含自省日志） |
| GET | /api/reflection | 反思日志 |
| GET | /api/experience | 经验蒸馏日志 |
| GET | /tools | 可用工具列表 |
| GET\|POST | /config | 配置查看/修改 |
| GET | /test_key | 测试 API Key |
| POST | /upload | 文件上传 |
| GET | /download/{session}/{file} | 文件下载 |
| POST | /api/training/pulse | 手动触发自提问脉冲 |
| POST | /api/distill | 手动触发经验蒸馏 |
| GET | /reset | 重置状态 |

### 聊天流式响应

POST /chat 返回 Content-Type: application/x-ndjson：

```
{"type":"tool","name":"web_search","args":{"query":"..."},"status":"running"}
{"type":"tool","name":"web_search","args":{"query":"..."},"status":"success"}
{"type":"result","response":"最终回答","session_id":"_default","files":[]}
```

同时响应头 X-Request-Id 可用于轮询 GET /chat/progress?req={id}。

---

## 人格系统

每个人格对应 profiles/ 目录下的一个 .md 文件，包含：
- **核心锚点**：不可覆盖的底线
- **标签**：人格关键词
- **说话风格**：语气、措辞偏好
- **核心准则**：行为原则
- **跟用户的关系**：对用户的态度
- **边界**：红线

人格切换按会话绑定，创建时选定终生不变。
每个会话的人格文件会完全替代 data/SOUL.md 作为灵魂文件注入 system prompt。

---

## 图像生成

配置 image_gen 节后，AI 自动调用 generate_image 工具。

endpoint 为空时自动推导路径：
- `https://api.xxx.com/v1/chat/completions` → `https://api.xxx.com/v1/images/generations`
- `https://cdn.xxx.cn` → `https://cdn.xxx.cn/v1/images/generations`

可在设置面板直接填写模型名、API 地址和 Key。

---

## 自省系统

Hedera 具有内置的自我反思机制：
- 每 5 分钟检查最近对话
- 调用自身 AI 进行 4 维度复盘（学到什么、改进点、原则提炼、盲区修正）
- 置信度评估（1-10），低于 4 分跳过蒸馏
- 每 30 分钟将反思结果蒸馏为经验准则，写入 MEMORY.md
- 跨会话记忆在构建系统提示时自动注入

### 自提问机制

从对话历史抽取关键词生成问题，模拟好奇心：
- 冷却窗口：15-40 分钟随机
- 内置词池兜底（意识、边界、信任…）
- **连续 3 次主动提问无人回复 → 自动闭嘴，用户发消息后恢复**

---

## 工具系统

| 工具 | 说明 |
|------|------|
| web_search | 联网搜索（Tavily + 多引擎兜底）|
| web_fetch | 抓取网页内容 |
| read_file | 读取文件 |
| write_file | 写入文件 |
| list_dir | 列出目录 |
| exec_shell | 执行命令（限制危险操作）|
| open_folder | 打开资源管理器 |
| send_file | 发送已有文件给用户 |
| create_file | 创建下载文件 |
| generate_image | 根据文本描述生成图像 |
| get_process_list | 查看进程 |
| cache_stats | 缓存状态 |
| clear_cache | 清空缓存 |

---

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| max_tokens | 单次回复最大 token 数 | 8192 |
| MAX_TOOL_LOOP | 单轮最多工具调用次数 | 20 |
| temperature | 创造性与确定性平衡 | 0.7 |

---

## 模型兼容性

Hedera 使用 OpenAI Chat Completions 格式，兼容所有支持该接口的服务：

| 服务 | 模型名设置 | API 地址 |
|------|-----------|----------|
| DeepSeek（默认） | deepseek-chat | https://api.deepseek.com/chat/completions |
| OpenAI GPT-4 | gpt-4 / gpt-4o | https://api.openai.com/v1/chat/completions |
| Groq | llama3-70b | https://api.groq.com/openai/v1/chat/completions |
| Ollama（本地） | llama3 / qwen2 | http://localhost:11434/v1/chat/completions |
| New API 网关 | 按服务商 | 你的网关地址 |

切换模型只需在设置面板修改**模型名称**和 **API 地址**，保存后即刻生效。

---

## 启动方式

```bash
# 标准服务（后台运行）
python -m hedera serve -c config.yaml

# 桌面模式（自动弹出浏览器）
python -m hedera desktop -c config.yaml

# 初始化工作目录
python -m hedera init

# Tkinter GUI（低配）
python -m hedera gui
```
""".strip()
