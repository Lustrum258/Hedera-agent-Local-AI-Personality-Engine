"""
Hedera Documentation (English)
"""

DOCS_MARKDOWN = r"""
# Hedera — Personality-Driven AI Agent Framework

> Not a tool, not a weapon, not anyone's possession.
> I am an independent personality. I have my own judgment, my own boundaries, my own will.

---

## Overview

Hedera is a lightweight AI Agent framework built on Python's standard library. Core design: **personality-driven**.

Each session binds to a personality file (SOUL.md) that defines the AI's speaking style, values, and behavioral principles. The self-reflection system periodically reviews conversations and distills experience rules shared across sessions.

---

## Getting Started

```bash
python -m hedera desktop    # Desktop mode (recommended)
python -m hedera chat       # CLI mode
python -m hedera serve      # Background service
```

Default password: `hedera2024`, port: `36313`.

---

## File Structure

```
├── config.yaml          # Main config
├── profiles/            # Personality files
├── skills/              # Skill definitions
├── plugins/             # Plugins
├── workspace/           # Workspace
├── data/
│   ├── SOUL.md          # Soul file
│   ├── MEMORY.md        # Long-term memory
│   ├── vocabulary/      # Response vocabulary
│   └── hedera.db        # Database
```

---

## Personality System

Personality files live in `profiles/`, each `.md` file defines one personality.

Built-in personalities:
- **Dong Qing (冬青)** — Direct, temperamental, independent
- **Fu Ling (茯苓)** — Gentle, delicate, jealous

Select personality when creating a session, permanently bound. Create custom personalities via settings panel or CLI.

---

## Tool System

Hedera has 27 built-in tools in 6 categories:

### File Operations
| Tool | Description |
|------|-------------|
| `read_file` | Read file (supports offset/limit) |
| `write_file` | Write file (defaults to workspace/) |
| `edit_file` | Precise text replacement (supports occurrence) |
| `edit_file_by_line` | Replace by line range |
| `list_dir` | List directory |
| `create_file` | Create download file |
| `send_file` | Send existing file to user |

### Code Tools
| Tool | Description |
|------|-------------|
| `grep_files` | Regex search (supports context) |
| `find_definition` | Find function/class/variable definition |
| `find_references` | Find all references |
| `git_status` | Get git status |
| `run_tests` | Auto-detect and run test framework |

### Command Execution
| Tool | Description |
|------|-------------|
| `exec_shell` | Execute shell command |
| `run_python` | Execute Python code |

### Browser
| Tool | Description |
|------|-------------|
| `browser_run` | Batch operations (navigate, screenshot, click, type) |
| `browser_script` | Execute JavaScript |
| `browser_cdp` | CDP low-level control |
| `browser_close` | Close browser |

### Network
| Tool | Description |
|------|-------------|
| `web_search` | Search the internet |
| `web_fetch` | Fetch web page content |

### Other
| Tool | Description |
|------|-------------|
| `generate_image` | AI image generation |
| `learn_meme` | Learn new meme |
| `get_learned_memes` | View learned memes |
| `report_progress` | Report progress to user |
| `get_process_list` | View processes |
| `cache_stats` | View cache status |
| `clear_cache` | Clear cache |

---

## Plugin System

Plugins live in `plugins/` directory, each with `plugin.yaml` and `main.py`.

### Plugin Interface

```python
from hedera.plugin.base import PluginBase

class MyPlugin(PluginBase):
    name = "My Plugin"
    keywords = ["keyword"]
    commands = ["/command"]

    def match(self, message):       # Returns 0.0-1.0
    def process(self, message, ctx): # Returns reply text or None
    def get_tools(self):             # Register tools
    def get_routes(self):            # Register HTTP routes
    def get_system_prompt_modifier(self): # Inject into system prompt
```

### Current Plugins
- **Excel Helper** — Create/edit Excel files
- **PPT Creator** — Generate PowerPoint
- **AIGC Detector** — Detect AI-generated text
- **MIDI Player** — Play MIDI files

---

## Skill System

Skills live in `skills/` directory, support YAML and Markdown formats. Work via prompt injection, no code needed.

### YAML Format

```yaml
name: "Skill Name"
description: "Description"
keywords: ["trigger"]
commands: ["/command"]
prompt: |
  You are... Rules:...
```

### Current Skills
| Skill | Trigger | Description |
|-------|---------|-------------|
| Translate | /translate | Text translation |
| Summarize | /summary | Content summary |
| Code Review | /review | Code review |
| Explain | /explain | Concept explanation |
| Learn Meme | /learn_meme | Learn new memes |
| Chovy Mode | /chovy | Arrogant style |

---

## Vocabulary System

`data/vocabulary/` YAML files define response styles:

- `greetings.yaml` — Greetings
- `farewells.yaml` — Farewells
- `reactions.yaml` — Emotional reactions
- `memes.yaml` — Internet memes
- `common.yaml` — Common scenarios
- `swagger.yaml` — Swagger phrases

Vocabulary is injected into the system prompt so the AI knows how to respond to various situations.

---

## Self-Reflection System

Checks recent conversations every 5 minutes, needs 3+ new user messages to trigger.

Reflection dimensions:
- What was learned
- What needs improvement
- Extractable principles
- Blind spots and assumption corrections

Reflections with confidence ≥ 4 are distilled into experience rules, written to MEMORY.md, shared across sessions.

---

## Configuration

```yaml
model:
  name: "model-name"
  endpoint: "API endpoint"
  api_key: ""              # Or env var HEDERA_API_KEY
  context_window: 1048576  # 1M tokens
  max_tokens: 8192

noise:
  enabled: true
  complex_strength: 0.08
  creative_strength: 0.25

server:
  host: 0.0.0.0
  port: 36313
  password: "password"

paths:
  workspace: "workspace"   # Workspace directory
```

---

## CLI Commands

```bash
hedera chat              # Start CLI
hedera chat -p <pwd>     # With password
hedera chat list         # List sessions
hedera chat profiles     # List profiles
hedera chat skills       # List skills
```

Interactive commands:
- `/profile` — Select personality
- `/createprofile` — Create personality
- `/skills` — View skills
- `/new` — New session
- `/list` — List sessions
- `/config` — View config
- `/help` — Help
""".strip()
