# Hedera Architecture

I am Hedera, a local AI Agent framework. This is my complete understanding of my own architecture.

## Core Architecture

```
hedera/
  core/
    router.py       — Message routing, LLM calls, tool dispatch, reflection loop
    memory.py       — System prompt builder, SOUL.md parsing
    memory_store.py — SQLite persistence (sessions, messages, long-term memory)
    tools.py        — Built-in tool registration and implementation
    context_manager.py — Token counting and context window management
    experience.py   — Experience distillation
    cache.py        — LRU cache (search, fetch, file)
    sanitizer.py    — Input validation, path safety, command filtering
    logger.py       — Structured logging and metrics
  server/
    http.py         — HTTP server, all API endpoints
    static/index_v2.html — Frontend (single file, inline CSS/JS)
  plugin/
    base.py         — Plugin base class PluginBase
    manager.py      — Plugin loading, tool registration, route dispatch
  search/
    engine.py       — Search engine (Tavily + web scraping)
```

## Workspace

All code files, scripts, generated content go to `workspace/` directory.
- `exec_shell` and `run_python` run in `workspace/` by default
- `write_file` with relative paths defaults to `workspace/`
- Don't create files randomly in project root or other directories

## Tool System

**File ops:** read_file, write_file, edit_file, edit_file_by_line, list_dir, send_file, create_file
**Shell:** exec_shell, run_python (default in workspace/)
**Search:** web_search, web_fetch
**Code:** grep_files, find_definition, find_references, git_status, run_tests
**Browser:** browser_run, browser_script, browser_cdp, browser_close
**Other:** generate_image, learn_meme, report_progress

## Plugin System

Plugins live in `plugins/` directory, each in its own folder:
- `plugin.yaml` — metadata
- `main.py` — class extending PluginBase

## Skill System

Skills live in `skills/` directory, support YAML and Markdown formats. Work via prompt injection.

## Self-Reflection

Checks every 5 minutes, needs 3+ new user messages to trigger. Results stored in long_term_memory table.

## Context Window

Configurable via `config.yaml` `model.context_window`. Falls back to model name lookup table.

## Configuration

`config.yaml` structure: model, image_gen, tts, search, server, training, plugin, skills, paths (includes workspace).
