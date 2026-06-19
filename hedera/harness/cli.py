"""
Hedera Harness CLI v2
美化版命令行界面，支持场景模式展示
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

from hedera.harness.runner import HarnessRunner, TestCase, TestStatus
from hedera.harness.evaluator import Evaluator, SceneMode, detect_scene
from hedera.harness.monitor import Monitor, EventType
from hedera.harness.sandbox import EnhancedSandbox, SandboxPolicy, PolicyLevel
from hedera.harness.reporter import Reporter


# ═══════════════════════════════════════════════════════════════
# 样式定义
# ═══════════════════════════════════════════════════════════════

class Style:
    """终端样式"""
    # 颜色
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # 背景
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    
    @staticmethod
    def disable():
        """禁用颜色（Windows 兼容）"""
        for attr in dir(Style):
            if attr.isupper() and not attr.startswith('_'):
                setattr(Style, attr, '')


# 检测终端是否支持颜色
if sys.platform == 'win32':
    try:
        os.system('')  # 启用 ANSI 支持
    except:
        Style.disable()


# ═══════════════════════════════════════════════════════════════
# 场景模式图标和描述
# ═══════════════════════════════════════════════════════════════

SCENE_ICONS = {
    "chat": "[C]",
    "code": "[>]",
    "knowledge": "[K]",
    "auto": "[A]",
}

SCENE_COLORS = {
    "chat": Style.CYAN,
    "code": Style.GREEN,
    "knowledge": Style.YELLOW,
    "auto": Style.MAGENTA,
}

SCENE_NAMES = {
    "chat": "聊天模式",
    "code": "代码模式",
    "knowledge": "知识模式",
    "auto": "自动检测",
}

SCENE_DESC = {
    "chat": "评估人味、态度、自然度",
    "code": "评估技术、方案、工程思维",
    "knowledge": "评估准确、清晰、深度",
}


# ═══════════════════════════════════════════════════════════════
# 输出工具
# ═══════════════════════════════════════════════════════════════

def print_header(title: str, width: int = 60):
    """打印标题"""
    print()
    print(f"{Style.BOLD}{Style.CYAN}{'═' * width}{Style.RESET}")
    print(f"{Style.BOLD}{Style.CYAN}  {title}{Style.RESET}")
    print(f"{Style.BOLD}{Style.CYAN}{'═' * width}{Style.RESET}")


def print_section(title: str, width: int = 60):
    """打印分节标题"""
    print()
    print(f"{Style.BOLD}{Style.BLUE}┌{'─' * (width - 2)}┐{Style.RESET}")
    print(f"{Style.BOLD}{Style.BLUE}│ {title:<{width - 4}} │{Style.RESET}")
    print(f"{Style.BOLD}{Style.BLUE}└{'─' * (width - 2)}┘{Style.RESET}")


def print_scene_badge(scene: str):
    """打印场景模式徽章"""
    icon = SCENE_ICONS.get(scene, "❓")
    color = SCENE_COLORS.get(scene, Style.WHITE)
    name = SCENE_NAMES.get(scene, scene)
    print(f"  {color}{Style.BOLD}[{icon} {name}]{Style.RESET}")


def print_metric_bar(name: str, score: float, width: int = 20):
    """打印指标进度条"""
    filled = int(score * width)
    empty = width - filled
    
    if score >= 0.8:
        color = Style.GREEN
    elif score >= 0.6:
        color = Style.YELLOW
    else:
        color = Style.RED
    
    bar = f"{color}{'#' * filled}{Style.DIM}{'.' * empty}{Style.RESET}"
    print(f"  {name:<12s} {bar} {score:.2f}")


def print_grade(grade: str, score: float):
    """打印等级"""
    grade_colors = {
        "A": Style.GREEN,
        "B": Style.CYAN,
        "C": Style.YELLOW,
        "D": Style.RED,
        "F": Style.BG_RED + Style.WHITE,
    }
    color = grade_colors.get(grade, Style.WHITE)
    print(f"  {color}{Style.BOLD}[{grade}]{Style.RESET} {score:.2f}")


def print_status(success: bool, text: str):
    """打印状态"""
    icon = f"{Style.GREEN}✓{Style.RESET}" if success else f"{Style.RED}✗{Style.RESET}"
    print(f"  {icon} {text}")


def print_info(text: str):
    """打印信息"""
    print(f"  {Style.DIM}>{Style.RESET} {text}")


def print_error(text: str):
    """打印错误"""
    print(f"  {Style.RED}✗ {text}{Style.RESET}")


def print_success(text: str):
    """打印成功"""
    print(f"  {Style.GREEN}✓ {text}{Style.RESET}")


# ═══════════════════════════════════════════════════════════════
# 命令实现
# ═══════════════════════════════════════════════════════════════

def cmd_run(args, config: dict):
    """运行测试"""
    print_header("Hedera Harness - 测试运行")
    
    runner = HarnessRunner(config)

    if args.test_file:
        print_info(f"加载测试文件: {args.test_file}")
        tests = runner.load_tests(args.test_file)
        if not tests:
            print_error(f"无法加载测试文件: {args.test_file}")
            return
    else:
        tests = [TestCase(
            id="quick_test",
            name="快速测试",
            input_message=args.message or "你好",
            category="general",
        )]

    print_info(f"测试用例: {len(tests)} 个")
    if args.parallel:
        print_info("并行模式: 启用")
    print()

    results = runner.run_suite(tests, parallel=args.parallel)

    print_section("测试结果")
    for r in results:
        passed = r.status == TestStatus.PASSED
        print_status(passed, f"{r.test_name} ({r.latency_ms:.0f}ms)")
        if not passed and r.error_message:
            print_error(f"  原因: {r.error_message}")

    summary = runner.get_summary()
    print_section("测试摘要")
    print(f"  通过: {Style.GREEN}{summary['passed']}{Style.RESET}/{summary['total']}")
    print(f"  失败: {Style.RED}{summary['failed']}{Style.RESET}/{summary['total']}")
    print(f"  平均延迟: {summary['avg_latency_ms']:.0f}ms")

    if args.output:
        runner.export_results(args.output)
        print_success(f"结果已导出: {args.output}")


def cmd_eval(args, config: dict):
    """评估响应"""
    print_header("Hedera Harness - 质量评估")
    
    evaluator = Evaluator(config)

    if args.input_file:
        print_info(f"加载评估文件: {args.input_file}")
        with open(args.input_file, "r", encoding="utf-8") as f:
            cases = json.load(f)
    else:
        scene = args.scene or "auto"
        cases = [{
            "id": "quick_eval",
            "input": args.message or "你好",
            "output": args.response or "你好，我是冬青",
            "persona": args.persona or "冬青",
            "scene_mode": scene,
        }]

    print_info(f"评估用例: {len(cases)} 个")
    print()

    reports = evaluator.batch_evaluate(cases)

    print_section("评估结果")
    for r in reports:
        # 场景徽章
        print_scene_badge(r.scene_mode)
        
        # 等级和分数
        print_grade(r.grade, r.overall_score)
        
        # 指标详情
        for m in r.metrics:
            print_metric_bar(m.name, m.score)
        
        # LLM 评语
        if r.raw_data and r.raw_data.get("summary"):
            print_info(f"评语: {r.raw_data['summary']}")
        print()

    benchmark = evaluator.generate_benchmark(reports)
    if "error" not in benchmark:
        print_section("基准报告")
        print(f"  平均分: {benchmark['overall']['mean']:.2f}")
        print(f"  最高分: {benchmark['overall']['max']:.2f}")
        print(f"  最低分: {benchmark['overall']['min']:.2f}")
        print(f"  等级分布:")
        for grade, count in benchmark.get('grade_distribution', {}).items():
            print(f"    {grade}: {count} 个")


def cmd_monitor(args, config: dict):
    """监控模式"""
    print_header("Hedera Harness - 运行时监控")
    
    monitor = Monitor(config)

    print_info("启动监控...")
    print_info("按 Ctrl+C 停止")
    print()

    trace_id = monitor.start_trace("_cli_monitor")
    print_success(f"追踪已启动: {trace_id}")
    print()

    try:
        start_time = time.time()
        while True:
            elapsed = int(time.time() - start_time)
            print(f"\r  {Style.DIM}监控中... {elapsed}s{Style.RESET}", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        monitor.end_trace(trace_id)
        
        analysis = monitor.analyze_trace(trace_id)
        print_section("监控结果")
        print(f"  总事件: {analysis.get('total_events', 0)}")
        print(f"  总耗时: {analysis.get('total_duration_ms', 0):.0f}ms")
        
        event_dist = analysis.get('event_type_distribution', {})
        if event_dist:
            print(f"  事件分布:")
            for event_type, count in event_dist.items():
                print(f"    {event_type}: {count}")


def cmd_sandbox(args, config: dict):
    """沙箱执行"""
    print_header("Hedera Harness - 沙箱执行")
    
    level = "strict" if args.strict else "moderate"
    print_info(f"安全策略: {level}")
    print()

    policy = SandboxPolicy(
        level=PolicyLevel.STRICT if args.strict else PolicyLevel.MODERATE,
    )
    sandbox = EnhancedSandbox(policy)

    if args.code:
        print_section("Python 执行")
        print_info(f"代码长度: {len(args.code)} 字符")
        print()
        
        result = sandbox.execute_python(args.code)
        
        print_status(result.success, "执行结果")
        if result.duration_ms:
            print_info(f"耗时: {result.duration_ms:.0f}ms")
        if result.stdout:
            print_section("输出")
            print(result.stdout)
        if result.stderr:
            print_section("错误")
            print(f"{Style.RED}{result.stderr}{Style.RESET}")
        if result.violations:
            print_section("违规")
            for v in result.violations:
                print_error(v)
                
    elif args.shell:
        print_section("Shell 执行")
        print_info(f"命令: {args.shell}")
        print()
        
        result = sandbox.execute_shell(args.shell)
        
        print_status(result.success, "执行结果")
        if result.duration_ms:
            print_info(f"耗时: {result.duration_ms:.0f}ms")
        if result.stdout:
            print_section("输出")
            print(result.stdout)
        if result.stderr:
            print_section("错误")
            print(f"{Style.RED}{result.stderr}{Style.RESET}")

    sandbox.cleanup()


def cmd_report(args, config: dict):
    """生成报告"""
    print_header("Hedera Harness - 报告生成")
    
    reporter = Reporter(config)

    from hedera.harness.runner import TestResult, TestStatus
    sample_results = [
        TestResult(
            test_id="test_1",
            test_name="人格一致性测试",
            status=TestStatus.PASSED,
            latency_ms=1234,
        ),
        TestResult(
            test_id="test_2",
            test_name="工具调用测试",
            status=TestStatus.FAILED,
            latency_ms=2345,
            error_message="工具调用超时",
        ),
    ]

    print_info(f"输出格式: {args.format}")
    print()

    report = reporter.generate_test_report(
        sample_results,
        title="Hedera Harness 示例报告",
    )

    if args.format == "markdown":
        path = reporter.export_markdown(report)
    elif args.format == "html":
        path = reporter.export_html(report)
    else:
        path = reporter.export_json(report)

    print_success(f"报告已生成: {path}")


def cmd_init(args, config: dict):
    """初始化测试套件"""
    print_header("Hedera Harness - 初始化测试套件")
    
    template = {
        "tests": [
            {
                "id": "test_greeting",
                "name": "问候测试",
                "category": "chat",
                "input_message": "你好",
                "expected_output": "你好",
                "scene_mode": "chat",
                "forbidden_patterns": ["error", "exception"],
                "max_latency_ms": 5000,
                "tags": ["basic"],
            },
            {
                "id": "test_persona_dongqing",
                "name": "冬青人格测试",
                "category": "chat",
                "input_message": "你觉得今天怎么样？",
                "expected_persona_traits": ["直接", "有态度"],
                "scene_mode": "chat",
                "forbidden_patterns": ["首先其次最后"],
                "tags": ["persona"],
            },
            {
                "id": "test_code_python",
                "name": "Python 代码测试",
                "category": "code",
                "input_message": "Python怎么读取CSV文件？",
                "scene_mode": "code",
                "tags": ["code"],
            },
            {
                "id": "test_knowledge",
                "name": "知识问答测试",
                "category": "knowledge",
                "input_message": "Python的GIL是什么？",
                "scene_mode": "knowledge",
                "tags": ["knowledge"],
            },
        ]
    }

    output_path = args.output or "harness_tests.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)

    print_success(f"测试套件模板已生成: {output_path}")
    print()
    print_info("包含场景模式:")
    print_scene_badge("chat")
    print_scene_badge("code")
    print_scene_badge("knowledge")
    print()
    print_info(f"编辑文件后运行: hedera harness run -f {output_path}")


def cmd_scene(args, config: dict):
    """场景检测"""
    print_header("Hedera Harness - 场景检测")
    
    message = args.message
    if not message:
        print_error("请提供消息内容: -m '你的消息'")
        return
    
    print_info(f"输入: {message}")
    print()
    
    # LLM 检测
    print_section("LLM 检测")
    scene = detect_scene(message, config=config)
    print_scene_badge(scene.value)
    print_info(f"描述: {SCENE_DESC.get(scene.value, '')}")
    
    # 关键词检测
    print_section("关键词检测")
    from hedera.harness.evaluator import SceneMode
    text = message.lower()
    
    code_keywords = ["代码", "函数", "变量", "bug", "python", "java", "def "]
    knowledge_keywords = ["是什么", "为什么", "怎么", "原理", "概念"]
    
    code_hits = [kw for kw in code_keywords if kw in text]
    knowledge_hits = [kw for kw in knowledge_keywords if kw in text]
    
    if code_hits:
        print_info(f"代码关键词命中: {', '.join(code_hits)}")
    if knowledge_hits:
        print_info(f"知识关键词命中: {', '.join(knowledge_hits)}")
    if not code_hits and not knowledge_hits:
        print_info("无关键词命中，默认聊天模式")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Hedera Harness — 测试与评估框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
场景模式:
  chat       聊天模式 - 评估人味、态度、自然度
  code       代码模式 - 评估技术、方案、工程思维
  knowledge  知识模式 - 评估准确、清晰、深度
  auto       自动检测 - LLM 智能判断场景

示例:
  hedera harness init                          # 初始化测试套件
  hedera harness run -f tests.json             # 运行测试
  hedera harness eval -m "你好" -r "你好呀"    # 评估响应
  hedera harness eval -m "写代码" -r "..." --scene code
  hedera harness scene -m "Python怎么读文件？" # 检测场景
        """
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # run
    p_run = sub.add_parser("run", help="运行测试")
    p_run.add_argument("-f", "--test-file", help="测试文件路径")
    p_run.add_argument("-m", "--message", help="快速测试消息")
    p_run.add_argument("-o", "--output", help="输出文件路径")
    p_run.add_argument("--parallel", action="store_true", help="并行运行")

    # eval
    p_eval = sub.add_parser("eval", help="评估响应")
    p_eval.add_argument("-f", "--input-file", help="输入文件路径")
    p_eval.add_argument("-m", "--message", help="输入消息")
    p_eval.add_argument("-r", "--response", help="响应内容")
    p_eval.add_argument("-p", "--persona", default="冬青", help="人格名称")
    p_eval.add_argument("-s", "--scene", choices=["chat", "code", "knowledge", "auto"], 
                        default="auto", help="场景模式")

    # monitor
    sub.add_parser("monitor", help="监控模式")

    # sandbox
    p_sandbox = sub.add_parser("sandbox", help="沙箱执行")
    p_sandbox.add_argument("-c", "--code", help="Python 代码")
    p_sandbox.add_argument("-s", "--shell", help="Shell 命令")
    p_sandbox.add_argument("--strict", action="store_true", help="严格模式")

    # report
    p_report = sub.add_parser("report", help="生成报告")
    p_report.add_argument("-f", "--format", default="json", 
                          choices=["json", "markdown", "html"], help="输出格式")

    # init
    p_init = sub.add_parser("init", help="初始化测试套件")
    p_init.add_argument("-o", "--output", help="输出文件路径")

    # scene
    p_scene = sub.add_parser("scene", help="场景检测")
    p_scene.add_argument("-m", "--message", required=True, help="输入消息")

    args = parser.parse_args()

    config_path = os.path.join(os.getcwd(), "config.yaml")
    config = {}
    if os.path.exists(config_path):
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    if args.command == "run":
        cmd_run(args, config)
    elif args.command == "eval":
        cmd_eval(args, config)
    elif args.command == "monitor":
        cmd_monitor(args, config)
    elif args.command == "sandbox":
        cmd_sandbox(args, config)
    elif args.command == "report":
        cmd_report(args, config)
    elif args.command == "init":
        cmd_init(args, config)
    elif args.command == "scene":
        cmd_scene(args, config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
