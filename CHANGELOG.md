# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.7.0] - 2026-06-03

### 新增
- 上下文管理器：基于 token 的智能截断（支持 1M 上下文窗口）
- `find_definition` 工具：查找函数/类/变量定义位置
- `grep_files` 新增 `context` 参数：显示匹配行上下文
- `edit_file` 新增 `occurrence` 参数：精确替换第 N 个匹配
- `edit_file` 返回 unified diff：编辑后自动显示变更
- 前端设置面板 Tab 化：LLM / 图片 / TTS / 搜索分 Tab 显示
- 前端配置摘要：设置面板顶部显示当前生效配置
- 前端预设卡片化：预设以卡片形式展示，一键应用
- 前端自动保存：输入后 300ms 自动保存，支持 blur/粘贴/回车即时保存
- 自省系统修复：从正确的用户会话读取历史（之前读的是空的 _reflection session）
- 后台标签恢复：断连后持续轮询后端，不再直接显示"连接失败"

### 修复
- config 跨会话污染：人格切换后 config 不再被永久修改（try/finally 保护）
- clear_all_sessions 误删系统会话：排除列表增加 _default, _experience, _admin
- delete_session 遗漏清理：补上 slider_snapshots 清理
- 浏览器自动填充：设置输入框加 autocomplete="new-password" 防止密码被填入 API Key
- run_python 验证绕过：修复 validate_shell_command 无效的安全检查
- _list_dir 路径错误：使用安全路径替代原始路径

### 优化
- 工具响应截断限制：从 4000 提升到 15000 字符
- read_file 截断：从 4000 字符改为 200 行 + 分段提示
- 工具提示：包含参数描述（之前只有参数名）
- git_status 缓存：30 秒 TTL 避免重复调用
- 代码工作流指令：四阶段工作流（理解→修改→验证→收尾）
- 代码风格匹配：新增系统提示要求匹配现有代码风格

## [0.6.0] - 2026-05-30

### 新增
- 上下文用量显示
- 经验蒸馏质量检查
- 多人格支持（冬青、茯苓）

## [0.5.0] - 2026-05-20

### 新增
- 初始版本发布
- 人格系统
- 自省机制
- 噪声层
- 工具系统
- 插件架构
