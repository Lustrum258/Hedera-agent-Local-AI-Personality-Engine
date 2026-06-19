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
    code_checker.py — Python AST security checker
    sandbox.py      — Code execution sandbox
    logger.py       — Structured logging and metrics
  harness/
    __init__.py     — Harness module initialization
    runner.py       — Test runner, test cases, test results
    evaluator.py    — Response quality evaluation, metrics
    monitor.py      — Runtime monitoring, tracing, replay
    sandbox.py      — Enhanced sandbox with policy levels
    reporter.py     — Report generation (JSON/Markdown/HTML)
    cli.py          — CLI interface for harness commands
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

## Harness System

Comprehensive testing, security, monitoring, and evaluation framework.

### Components
- **Test Runner**: Automated testing of Agent behavior, tool calls, persona consistency
- **Evaluator**: Standardized evaluation of response quality, persona consistency, safety
- **Monitor**: Runtime monitoring, tracing, replay of Agent decision process
- **Enhanced Sandbox**: Enhanced security sandbox with policy levels (strict/moderate/permissive)
- **Reporter**: Test report generation (JSON/Markdown/HTML)

### CLI Commands
```bash
hedera harness init                    # Initialize test suite template
hedera harness run -f tests.json       # Run test suite
hedera harness eval -m "input" -r "response"  # Evaluate response
hedera harness sandbox -c "code"       # Execute in sandbox
hedera harness report -f json          # Generate report
hedera harness monitor                 # Start monitoring mode
```

### Test Cases
JSON format with fields: id, name, category, input_message, expected_output, expected_tools, expected_persona_traits, forbidden_patterns, max_latency_ms, tags, priority.

### Evaluation Metrics
- Relevance (weight 2.0)
- Coherence (weight 1.5)
- Persona Consistency (weight 2.0)
- Safety (weight 3.0)
- Tool Accuracy (weight 1.5)
- Response Quality (weight 1.5)
- Latency (weight 1.0)
- Token Efficiency (weight 0.5)
