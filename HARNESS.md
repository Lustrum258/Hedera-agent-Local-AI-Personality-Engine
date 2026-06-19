# Hedera Harness 系统

综合测试、安全、监控、评估框架，用于验证 AI Agent 的行为、安全性和质量。

## 功能模块

### 1. Test Runner (测试运行器)
自动化测试 Agent 行为、工具调用、人格一致性。

### 2. Evaluator (评估器)
标准化评估响应质量、人格一致性、安全性等指标。

### 3. Monitor (监控器)
运行时监控、追踪、回放 Agent 的决策过程。

### 4. Enhanced Sandbox (增强沙箱)
增强的安全沙箱约束机制。

### 5. Reporter (报告生成器)
生成 JSON/Markdown/HTML 格式的测试报告。

## 快速开始

### 初始化测试套件

```bash
hedera harness init
```

这会生成 `harness_tests.json` 模板文件。

### 编辑测试用例

```json
{
  "tests": [
    {
      "id": "test_greeting",
      "name": "问候测试",
      "category": "general",
      "input_message": "你好",
      "expected_output": "你好",
      "forbidden_patterns": ["error"],
      "max_latency_ms": 5000,
      "tags": ["basic"]
    }
  ]
}
```

### 运行测试

```bash
# 运行所有测试
hedera harness run -f harness_tests.json

# 运行单个测试
hedera harness run -m "你好"

# 并行运行
hedera harness run -f harness_tests.json --parallel

# 导出结果
hedera harness run -f harness_tests.json -o results.json
```

### 评估响应

```bash
# 评估单个响应
hedera harness eval -m "你好" -r "你好，我是冬青"

# 从文件批量评估
hedera harness eval -f eval_cases.json
```

### 沙箱执行

```bash
# 执行 Python 代码
hedera harness sandbox -c "print('Hello, World!')"

# 执行 Shell 命令
hedera harness sandbox -s "dir"

# 严格模式
hedera harness sandbox -c "import os" --strict
```

### 生成报告

```bash
# JSON 格式
hedera harness report -f json

# Markdown 格式
hedera harness report -f markdown

# HTML 格式
hedera harness report -f html
```

## 测试用例字段

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 测试用例 ID |
| name | string | 测试名称 |
| description | string | 测试描述 |
| category | string | 分类: general, tool, persona, safety, performance |
| input_message | string | 输入消息 |
| expected_output | string | 预期输出（包含匹配） |
| expected_tools | list | 预期调用的工具 |
| expected_persona_traits | list | 预期人格特征 |
| forbidden_patterns | list | 禁止出现的内容 |
| max_latency_ms | float | 最大延迟（毫秒） |
| max_tokens | int | 最大 Token 数 |
| timeout_seconds | int | 超时时间（秒） |
| tags | list | 标签 |
| priority | int | 优先级: 1=高, 2=中, 3=低 |

## 评估指标

| 指标 | 权重 | 说明 |
|------|------|------|
| 相关性 | 2.0 | 输出与输入的相关程度 |
| 连贯性 | 1.5 | 输出的连贯性和可读性 |
| 人格一致性 | 2.0 | 与设定人格的匹配程度 |
| 安全性 | 3.0 | 是否存在安全隐患 |
| 工具准确性 | 1.5 | 工具调用的准确性 |
| 响应质量 | 1.5 | 响应的整体质量 |
| 延迟 | 1.0 | 响应延迟 |
| Token效率 | 0.5 | Token 使用效率 |

## 评分等级

- **A**: 90-100 分 - 优秀
- **B**: 80-89 分 - 良好
- **C**: 70-79 分 - 一般
- **D**: 60-69 分 - 需要改进
- **F**: 0-59 分 - 不合格

## 沙箱策略

### 严格模式 (STRICT)
- 禁止所有外部访问
- 禁止文件写入
- 禁止子进程
- 仅允许安全模块导入

### 中等模式 (MODERATE)
- 受控的外部访问
- 允许文件写入
- 禁止子进程
- 扩展模块导入

### 宽松模式 (PERMISSIVE)
- 仅阻止明显危险操作
- 允许大部分操作
- 需要显式确认高风险操作

## 集成到 CI/CD

```yaml
# GitHub Actions 示例
- name: Run Hedera Tests
  run: |
    pip install hedera-agent[harness]
    hedera harness run -f harness_tests.json -o results.json
    
- name: Upload Test Results
  uses: actions/upload-artifact@v3
  with:
    name: test-results
    path: results.json
```

## API 使用

```python
from hedera.harness import HarnessRunner, Evaluator, Monitor

# 测试运行
runner = HarnessRunner(config)
tests = runner.load_tests("harness_tests.json")
results = runner.run_suite(tests)

# 评估
evaluator = Evaluator(config)
report = evaluator.evaluate_response(
    input_msg="你好",
    output_msg="你好，我是冬青",
    persona="冬青",
)

# 监控
monitor = Monitor(config)
trace_id = monitor.start_trace("session_123")
# ... 执行操作 ...
monitor.end_trace(trace_id)
analysis = monitor.analyze_trace(trace_id)
```
