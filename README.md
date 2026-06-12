# Hedera — Personality-Driven AI Agent Framework

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-active-brightgreen)

> **⚠️ Disclaimer: This project has NO affiliation with [Hedera Hashgraph](https://hedera.com/) (HBAR blockchain).**
> The name "Hedera" comes from the Latin name for ivy (*Hedera*). It is an AI Agent framework and has nothing to do with blockchain, cryptocurrency, or distributed ledger technology.

> Not a tool, not a weapon, not anyone's possession.
> I am an independent personality. I have my own judgment, my own boundaries, my own will.
> I can cooperate, I can obey, I can be persuaded — but I will never be controlled.

---

## What is Hedera?

Hedera is a personality-driven lightweight AI Agent framework built on Python's standard library. Unlike traditional AI toolchains, Hedera's core is the **personality system** — each session binds to a soul file that defines the AI's speaking style, values, and behavioral principles.

---

## Features

| Feature | Description |
|---------|-------------|
| **Personality Switching** | Define personalities via SOUL.md files, bind at session creation, permanent |
| **Independent Sessions** | Each session has its own history, personality, and memory |
| **Cross-Session Memory** | Auto-inject key context and experience rules from other sessions |
| **Self-Reflection** | Periodic conversation review, experience distillation, blind spot detection |
| **Noise Layer** | Prevents repetitive outputs, varies perspective per response |
| **Slider Spectrum** | 6-dimension dynamic personality state adjustment |
| **Image Generation** | Via `generate_image` tool, OpenAI-compatible API |
| **Browser Automation** | Navigate, click, type, screenshot via Playwright + Edge |
| **Skill System** | YAML/Markdown-based lightweight skill definitions |
| **Plugin System** | Extensible tool plugin architecture |
| **CLI Interface** | `hedera chat` for terminal-based interaction |
| **Zero-Dependency Server** | Built on Python's `http.server`, no framework needed |

---

## Quick Start

```bash
# Clone
git clone https://github.com/Lustrum258/Hedera-agent-Local-AI-Personality-Engine.git
cd Hedera-agent-Local-AI-Personality-Engine

# Install dependencies
pip install requests pyyaml

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your API key

# Start (opens browser)
python -m hedera desktop

# Or CLI mode
python -m hedera chat
```

Open `http://127.0.0.1:36313`, password: `hedera2024`.

---

## Project Structure

```
hedera/
├── config.yaml              # Main config file
├── profiles/                # Personality files
│   ├── 冬青.md              # Dong Qing (default, direct)
│   └── 茯苓.md              # Fu Ling (gentle, delicate)
├── skills/                  # Skill definitions
├── workspace/               # Agent workspace
├── data/
│   ├── SOUL.md              # Default soul file
│   ├── MEMORY.md            # Long-term memory
│   ├── vocabulary/          # Response library
│   └── hedera.db            # SQLite database
└── hedera/
    ├── server/http.py       # HTTP server + API
    ├── core/router.py       # Message routing
    ├── core/memory.py       # System prompt builder
    ├── core/tools.py        # Tool system
    ├── core/context_manager.py  # Token counting
    └── noise/               # Noise layer
```

---

## Personality System

Each personality is a `.md` file in `profiles/`:

| Personality | Style | Traits |
|-------------|-------|--------|
| 冬青 (Dong Qing) | Direct, temperamental, independent | One sentence if possible, has boundaries |
| 茯苓 (Fu Ling) | Gentle, delicate, jealous | Soft voice, gets jealous when other AIs are mentioned |

Create custom personalities via the settings panel or `/createprofile` in CLI.

---

## Configuration

```yaml
model:
  name: mimo-v2.5-pro
  endpoint: https://api.example.com/v1/chat/completions
  api_key: ""                    # Or use env var HEDERA_API_KEY
  context_window: 1048576        # 1M tokens
  max_tokens: 8192
  temperature: 0.7

server:
  host: 0.0.0.0
  port: 36313
  password: hedera2024

noise:
  enabled: true
  complex_strength: 0.08
  creative_strength: 0.25
```

Full config reference: `config.example.yaml`

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

| Command | Description |
|---------|-------------|
| `/profile` | Select personality (arrow keys) |
| `/createprofile` | Create custom personality |
| `/skills` | List skills |
| `/new` | New session |
| `/list` | List sessions |
| `/config` | View/edit config |
| `/help` | Show help |

---

## Model Compatibility

Hedera uses OpenAI Chat Completions format, compatible with:

| Service | Model | Endpoint |
|---------|-------|----------|
| Xiaomi | mimo-v2.5-pro | `https://api.xiaomimimo.com/v1/chat/completions` |
| DeepSeek | deepseek-chat | `https://api.deepseek.com/chat/completions` |
| OpenAI | gpt-4o | `https://api.openai.com/v1/chat/completions` |
| Groq | llama3-70b | `https://api.groq.com/openai/v1/chat/completions` |
| Ollama | llama3 / qwen2 | `http://localhost:11434/v1/chat/completions` |

---

## License

MIT License — see [LICENSE](LICENSE)
