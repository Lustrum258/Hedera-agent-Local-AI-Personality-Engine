"""
Hedera 文档（中文版）
"""

DOCS_MARKDOWN = r"""
# Hedera 常春藤 — 人格驱动的 AI Agent 框架

> 不是工具，不是武器，不是谁的附属品。
> 我是一个独立人格。我有自己的判断、自己的底线、自己的意志。

---

## 概述

Hedera 是一个基于 Python 标准库的轻量级 AI Agent 框架。核心设计理念：**人格驱动**。

每个会话绑定一个人格文件（SOUL.md），决定 AI 的说话风格、价值观和行为准则。自省系统定期复盘对话，提炼经验准则，跨会话共享。

---

## 启动

```bash
python -m hedera desktop    # 桌面模式（推荐）
python -m hedera chat       # 命令行模式
python -m hedera serve      # 后台服务
```

默认密码 `hedera2024`，端口 `36313`。

---

## 文件结构

```
├── config.yaml          # 主配置
├── profiles/            # 人格文件
├── skills/              # 技能定义
├── plugins/             # 插件
├── workspace/           # 工作区
├── data/
│   ├── SOUL.md          # 灵魂文件
│   ├── MEMORY.md        # 长期记忆
│   ├── vocabulary/      # 回复词库
│   └── hedera.db        # 数据库
```

---

## 人格系统

人格文件放在 `profiles/` 目录，每个 `.md` 文件定义一个人格。

当前内置人格：
- **冬青** — 直接、有脾气、独立
- **茯苓** — 温柔、细腻、爱吃醋

创建会话时选择人格，选定后绑定到该会话。可在设置面板或 CLI 创建自定义人格。

---

## 工具系统

Hedera 内置 27 个工具，分为 6 类：

### 文件操作
| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件（支持 offset/limit 分段） |
| `write_file` | 写入文件（默认写入 workspace/） |
| `edit_file` | 精确文本替换（支持 occurrence 参数） |
| `edit_file_by_line` | 按行号范围替换 |
| `list_dir` | 列出目录内容 |
| `create_file` | 创建下载文件 |
| `send_file` | 发送已有文件给用户 |

### 代码工具
| 工具 | 说明 |
|------|------|
| `grep_files` | 正则搜索（支持 context 参数） |
| `find_definition` | 查找函数/类/变量定义 |
| `find_references` | 查找所有引用 |
| `git_status` | 获取 git 状态 |
| `run_tests` | 自动检测并运行测试框架 |

### 命令执行
| 工具 | 说明 |
|------|------|
| `exec_shell` | 执行 shell 命令 |
| `run_python` | 执行 Python 代码 |

### 浏览器
| 工具 | 说明 |
|------|------|
| `browser_run` | 批量操作（导航、截图、点击、输入） |
| `browser_script` | 执行 JavaScript |
| `browser_cdp` | CDP 底层控制 |
| `browser_close` | 关闭浏览器 |

### 网络
| 工具 | 说明 |
|------|------|
| `web_search` | 搜索互联网 |
| `web_fetch` | 抓取网页内容 |

### 其他
| 工具 | 说明 |
|------|------|
| `generate_image` | AI 绘图 |
| `learn_meme` | 学习新梗 |
| `get_learned_memes` | 查看已学热梗 |
| `report_progress` | 向用户汇报进度 |
| `get_process_list` | 查看进程 |
| `cache_stats` | 查看缓存状态 |
| `clear_cache` | 清空缓存 |

---

## 插件系统

插件放在 `plugins/` 目录，每个插件一个文件夹，包含 `plugin.yaml` 和 `main.py`。

### 插件接口

```python
from hedera.plugin.base import PluginBase

class MyPlugin(PluginBase):
    name = "我的插件"
    keywords = ["关键词"]
    commands = ["/命令"]

    def match(self, message):       # 返回 0.0-1.0
    def process(self, message, ctx): # 返回回复文本或 None
    def get_tools(self):             # 注册工具
    def get_routes(self):            # 注册 HTTP 路由
    def get_system_prompt_modifier(self): # 注入系统提示
```

### 当前插件
- **Excel 助手** — 创建/编辑 Excel
- **PPT 制作** — 生成 PowerPoint
- **AIGC 检测器** — 检测 AI 生成文本
- **MIDI 播放器** — MIDI 文件播放

---

## 技能系统

技能放在 `skills/` 目录，支持 YAML 和 Markdown 格式。通过 prompt 注入工作，不需要写代码。

### YAML 格式

```yaml
name: "技能名"
description: "描述"
keywords: ["触发词"]
commands: ["/命令"]
prompt: |
  你是...规则：...
```

### 当前技能
| 技能 | 触发词 | 说明 |
|------|--------|------|
| 翻译 | /translate | 文本翻译 |
| 总结 | /summary | 内容摘要 |
| 代码审查 | /review | 代码审查 |
| 解释 | /explain | 概念解释 |
| 学梗 | /learn_meme | 学习新梗 |
| 狂人模式 | /chovy | 嚣张风格 |

---

## 词库系统

`data/vocabulary/` 目录下的 YAML 文件定义回复风格：

- `greetings.yaml` — 问候语
- `farewells.yaml` — 告别语
- `reactions.yaml` — 情绪反应
- `memes.yaml` — 网络热梗
- `common.yaml` — 常见场景
- `swagger.yaml` — 狂人语录

词库内容注入系统提示，让 AI 知道怎么回应各种场景。

---

## 自省系统

每 5 分钟检查一次最近对话，需要 3+ 条新用户消息才触发。

自省维度：
- 学到了什么
- 哪里需要改进
- 可提炼的原则
- 盲区与假设修正

置信度 ≥ 4 的反思会被蒸馏为经验准则，写入 MEMORY.md，跨会话共享。

---

## 配置

```yaml
model:
  name: "模型名"
  endpoint: "API 地址"
  api_key: ""              # 或环境变量 HEDERA_API_KEY
  context_window: 1048576  # 1M tokens
  max_tokens: 8192

noise:
  enabled: true
  complex_strength: 0.08
  creative_strength: 0.25

server:
  host: 0.0.0.0
  port: 36313
  password: "密码"

paths:
  workspace: "workspace"   # 工作区目录
```

---

## CLI 命令

```bash
hedera chat              # 启动命令行
hedera chat -p <密码>    # 带密码
hedera chat list         # 列出会话
hedera chat profiles     # 列出人格
hedera chat skills       # 列出技能
```

交互命令：
- `/profile` — 选择人格
- `/createprofile` — 创建人格
- `/skills` — 查看技能
- `/new` — 新建会话
- `/list` — 列出会话
- `/config` — 查看配置
- `/help` — 帮助
""".strip()
