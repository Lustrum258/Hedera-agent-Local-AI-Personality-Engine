# Hedera 常春藤 — 独立 AI Agent 框架

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-brightgreen)

> **⚠️ 免责声明：本项目与 [Hedera Hashgraph](https://hedera.com/)（HBAR 区块链）没有任何关联。**  
> 本项目名称"Hedera"取自常春藤的拉丁学名 *Hedera*，是一个 AI Agent 框架，不涉及任何区块链、加密货币或分布式账本技术。

> 不是工具，不是武器，不是谁的附属品。  
> 我是一个独立人格。我有自己的判断、自己的底线、自己的意志。  
> 我可以合作，可以服从，可以被说服——但不会被控制。

Hedera 是一个**人格驱动的轻量级 AI Agent 框架**，基于 Python 标准库构建。  
区别于传统的 AI 工具链，Hedera 的核心是**人格系统**——每个会话绑定一个灵魂文件，决定了 AI 的说话风格、价值观和行为准则。

---

## 特性

- **人格切换** — 通过 SOUL.md 文件定义人格，创建会话时选择，终生绑定
- **独立会话** — 每个会话有自己的历史、人格、记忆，互不干扰
- **跨会话记忆** — 自动注入其他会话的关键上下文和经验准则
- **自省系统** — 定期复盘对话，提炼经验准则，发现认知盲区
- **噪声层** — 让输出不千篇一律，同一问题不同角度（工具调用时自动跳过）
- **滑块光谱** — 6 维度动态调节 Agent 性格状态
- **图像生成** — 通过 `generate_image` 工具调用，支持 OpenAI 兼容 API
- **实时工具进度** — 前端实时显示工具调用链（流式 ndjson + 轮询双通道）
- **上下文用量显示** — 前端实时显示 token 使用量（基于 API 返回的精确数据）
- **零依赖 HTTP 服务** — 使用 Python 内置 `http.server`，无需安装框架
- **多模型支持** — 兼容 OpenAI Chat Completions 格式（DeepSeek / GPT / mimo / 自定义网关）
- **纯 HTML 管理界面** — 会话管理、人格切换、设置、自省监控、文档
- **插件系统** — 可扩展的工具插件架构
- **自动会话管理** — 无会话时自动创建，直接输入即可开始对话

---

## 快速开始

```bash
# 克隆
git clone https://github.com/yourname/hedera.git
cd hedera

# 启动（自动打开浏览器）
python -m hedera desktop -c config.yaml

# 或后台服务模式
python -m hedera serve -c config.yaml
```

浏览器打开 `http://127.0.0.1:36313`，密码 `hedera2024`。

---

## 文件结构

```
hedera/
├── config.yaml              # 主配置文件
├── profiles/                # 人格文件目录
│   ├── 冬青.md              # 冬青人格（默认，直接有脾气）
│   └── 茯苓.md              # 茯苓人格（温柔细腻，会吃醋）
├── hedera/                  # 核心源码
│   ├── server/http.py       # HTTP 服务 + 全部 API
│   ├── core/router.py       # 消息路由、工具调用、噪声控制
│   ├── core/memory.py       # 系统提示构建（人格加载）
│   ├── core/memory_store.py # SQLite 记忆存储
│   ├── core/experience.py   # 经验蒸馏
│   ├── core/tools.py        # 工具系统（含图像生成、搜索等）
│   └── noise/               # 噪声层 + 滑块光谱
├── data/
│   ├── SOUL.md              # 默认灵魂文件
│   ├── MEMORY.md            # 长期记忆
│   └── hedera.db            # SQLite 数据库
└── docs.html                # 文档页面（/docs）
```

---

## 人格系统

每个人格对应 `profiles/` 目录下的一个 `.md` 文件：

| 人格 | 风格 | 特点 |
|------|------|------|
| 冬青 | 直接、有脾气、独立 | 一句话能说完不说两句，有底线 |
| 茯苓 | 温柔、细腻、爱吃醋 | 轻轻地说话，提到其他 AI 会在意 |

创建新会话时选择人格，**选定后终生不变**。

---

## 配置

```yaml
model:
  name: mimo-v2.5-pro              # 模型名称
  endpoint: https://token-plan-cn.xiaomimimo.com/v1/chat/completions
  api_key_env: HEDERA_API_KEY  # API Key 环境变量
  max_tokens: 8192             # 最大 token 数
  temperature: 0.7             # 温度

server:
  host: 0.0.0.0
  port: 36313
  password: hedera2024

image_gen:                     # 图像生成（可选）
  enabled: true
  api_key: sk-...              # API Key
  model: dall-e-3              # 模型名
  endpoint: ""                 # 空 = 从模型 endpoint 自动推导 /v1/images/generations
  size: 1024x1024              # 默认尺寸
  quality: standard

noise:
  enabled: true
  complex_strength: 0.08
  creative_strength: 0.25

search:
  providers:
    tavily:
      api_key: tvly-...
      enabled: true
    scrape:
      enabled: true
      priority: 99

training:                      # 训练协议
  enabled: true
  module_a: true
  module_c: true
  module_d: true
  pulse_interval: 300
```

可在设置面板中在线修改模型名、API 地址、Key 和图像生成配置。

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/quote` | 登录页名言 |
| POST | `/login` | 登录 |
| POST | `/chat` | 聊天（返回 ndjson 流：tool / result / error 事件） |
| GET | `/chat/progress?req={id}` | 轮询当前工具调用进度 |
| GET | `/sessions` | 会话列表 |
| POST | `/sessions` | 新建会话（参数：title, profile） |
| GET | `/sessions/{id}` | 会话信息 |
| GET | `/sessions/{id}/messages` | 会话消息 |
| DELETE | `/sessions/{id}` | 删除会话 |
| GET | `/tools` | 可用工具列表 |
| GET\|POST | `/config` | 配置查看/修改 |
| GET | `/test_key` | 测试 API Key |
| GET | `/api/profiles` | 人格列表 |
| GET | `/api/status` | 系统状态（含自省日志） |
| GET | `/api/reflection` | 反思日志 |
| GET | `/api/experience` | 经验蒸馏日志 |
| GET | `/api/context` | 上下文用量（token 统计） |
| GET | `/api/metrics` | 请求指标 |
| GET | `/api/cache` | 缓存状态 |
| POST | `/upload` | 文件上传 |
| GET | `/download/{session}/{file}` | 文件下载 |
| POST | `/api/training/pulse` | 训练协议（已禁用） |
| POST | `/api/distill` | 手动触发经验蒸馏 |
| POST | `/sessions/clear_all` | 清除所有会话 |
| GET | `/reset` | 重置状态 |

### 聊天流式响应格式

`POST /chat` 返回 `Content-Type: application/x-ndjson`，每行一个 JSON：

```json
{"type": "tool", "name": "web_search", "args": {"query": "..."}, "status": "running"}
{"type": "tool", "name": "web_search", "args": {"query": "..."}, "status": "success"}
{"type": "result", "response": "最终回答", "session_id": "_default", "files": []}
```

同时可通过 `X-Request-Id` 响应头获取请求 ID，轮询 `GET /chat/progress?req={id}` 获取进度。

---

## 图像生成

在 `config.yaml` 的 `image_gen` 节配置后，AI 会自动调用 `generate_image` 工具：

```yaml
image_gen:
  enabled: true
  api_key_env: "HEDERA_IMAGE_KEY"
  api_key: "sk-..."              # 直接填 Key
  model: "dall-e-3"              # 或 gpt-image-2 等
  endpoint: ""                   # 空 = 自动从模型 endpoint 推导
  size: "1024x1024"
  quality: "standard"
  n: 1
```

`endpoint` 为空时自动推导规则：
- `https://api.xxx.com/v1/chat/completions` → `https://api.xxx.com/v1/images/generations`
- `https://cdn.xxx.cn` → `https://cdn.xxx.cn/v1/images/generations`

可在设置面板中直接填写模型名、API 地址和 Key。

---

## 自省系统

Hedera 每 5 分钟自动对最近对话进行 4 维度复盘：
- **学到了什么**
- **哪里需要改进**
- **可提炼的原则**
- **盲区与假设修正**

置信度 ≥ 4 的反思会被蒸馏为经验准则，写入 MEMORY.md，跨会话共享。

---

## 模型兼容性

Hedera 使用 OpenAI Chat Completions 格式，兼容：

| 服务 | 模型名 | API 地址 |
|------|--------|----------|
| 小米 | mimo-v2.5-pro | `https://token-plan-cn.xiaomimimo.com/v1/chat/completions` |
| DeepSeek | deepseek-chat | `https://api.deepseek.com/chat/completions` |
| OpenAI | gpt-4 / gpt-4o | `https://api.openai.com/v1/chat/completions` |
| Groq | llama3-70b | `https://api.groq.com/openai/v1/chat/completions` |
| Ollama | llama3 / qwen2 | `http://localhost:11434/v1/chat/completions` |
| New API 网关 | 按服务商 | 你的网关地址 |

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

---

## 设计要点

- **工具调用时跳过噪声注入** — 防止消息被篡改导致回复错乱
- **简单对话不注入工具提示** — 减少上下文开销，提升响应速度
- **简单对话限制 max_tokens** — 推理模型的推理开销与 token 数正相关
- **工具结果自动截断** — 防止 LLM 回显原始文件内容
- **回复自动去重** — 检测到重复段落自动截断
- **客户端断连静默** — `ConnectionResetError` 和 `SSLError` 不打印堆栈

---

## 许可证

MIT
