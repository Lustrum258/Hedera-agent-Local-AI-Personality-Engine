# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## [0.7.0] - 2026-06-03

### Added
- Context manager: token-based smart truncation (supports 1M context window)
- `find_definition` tool: find function/class/variable definitions
- `grep_files` added `context` parameter: show surrounding lines
- `edit_file` added `occurrence` parameter: replace Nth match
- `edit_file` returns unified diff: auto-show changes after edit
- `run_tests` tool: auto-detect and run test frameworks
- `edit_file_by_line` tool: edit by line numbers
- `find_references` tool: find all usages of a symbol
- `browser_run` tool: batch browser operations
- Skill system: YAML/Markdown-based lightweight skills
- Workspace directory: code files default to workspace/
- Real-time token counting in CLI
- Settings panel redesign with tabs
- Config summary display
- Preset card UI
- Auto-save for settings (300ms debounce)
- Self-reflection fix: read from correct session
- Background tab recovery
- Plugin/Skill development guide

### Fixed
- Config cross-session pollution: try/finally protection
- clear_all_sessions deleting system sessions
- delete_session missing cleanup
- Browser autofill: autocomplete="new-password"
- run_python validation bypass
- _list_dir path error
- edit_file dead code
- Tool call display in wrong session
- Context window defaulting to 32K instead of model-specific value

### Optimized
- Tool response truncation: 4000 → 15000 chars
- read_file: 4000 chars → 200 lines + pagination
- Tool prompt includes parameter descriptions
- git_status cache (30s TTL)
- Code workflow: 4-phase instructions
- Code style matching
- Noise layer improvements
- Self-reflection now reads from user sessions
