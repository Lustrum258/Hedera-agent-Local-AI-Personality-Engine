# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## [0.8.1] - 2026-06-16

### Added
- WebUI 全面视觉升级
  - 全局噪点纹理覆盖层，增加质感
  - 毛玻璃效果（backdrop-filter）应用于所有卡片、输入框、弹窗
  - 渐变边框动画（gradientShift、borderGlow）
  - 自定义下拉组件，支持展开/收起动画
  - 侧边栏渐变背景、装饰光线、SVG 光晕
  - 消息气泡不对称圆角、渐变背景、顶部装饰线
  - 输入区毛玻璃背景、focus 三层光晕
  - 登录页双径向渐变背景、弹窗渐变边框
  - 设置弹窗毛玻璃 + 渐变边框
  - 按钮渐变底色 + 镜面光扫效果（shimmer）
  - 所有交互元素统一 hover 光晕动画
  - 会话项/人格项/工具项 hover 放大效果（scale 1.02）
  - 活跃会话项呼吸灯动画
  - CSS 变量系统（--glass、--glow-sm/md/lg）

- 自定义下拉组件
  - 语言切换器、人格选择器、预设选择器
  - 展开淡入 + 从上往下滑出动画
  - 选项 hover 高亮、选中项绿色光点指示器
  - 自定义 SVG 箭头（替换浏览器默认）

- 上下文栏 i18n 支持
  - 新增键：ctxLabel、ctxMessages、ctxIn、ctxOut、ctxMax、copyFailed
  - 支持全部 9 种语言

### Fixed
- API 流式响应双重 UTF-8 编码问题（resp.encoding = "utf-8"）
- 设置面板 Tab 选中时显示两条动画线（移除重复 border-bottom）
- 自省区域刷新按钮显示两个刷新符号
- 工具列表/自省区域文字对比度不足
- 设置页面输入框颜色不一致（统一为 rgba(14,14,22,.8)）
- 设置页面背光过强（降低光晕强度）
- 移除所有 UI 文字中的 emoji

### Optimized
- 清理冗余文件
  - 删除 14 个 __pycache__ 目录（约 1MB）
  - 删除 proxy.log
  - 删除 demo_harness.py、demo_tests.json
  - 删除 test_dedup_fix.py、test_harness.py、test_imports.py、test_real_api.py
  - 删除 harness_tests_example.json
  - 删除 migrate_keys.py

## [0.8.0] - 2026-06-14

### Added
- Harness System: 综合测试、安全、监控、评估框架
  - Test Runner: 自动化测试 Agent 行为、工具调用、人格一致性
  - Evaluator: 标准化评估响应质量、人格一致性、安全性等指标
  - Monitor: 运行时监控、追踪、回放 Agent 决策过程
  - Enhanced Sandbox: 增强的安全沙箱约束机制
  - Reporter: 测试报告生成器（JSON/Markdown/HTML）
  - CLI: `hedera harness` 命令行接口
- 测试用例模板生成: `hedera harness init`
- 批量测试运行: `hedera harness run -f tests.json`
- 响应质量评估: `hedera harness eval`
- 沙箱执行: `hedera harness sandbox`
- 报告生成: `hedera harness report`

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
