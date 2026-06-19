"""
Hedera Reporter
测试报告生成器
"""

import os
import json
import time
from typing import Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str = ""
    subsections: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    charts: list = field(default_factory=list)


@dataclass
class TestReport:
    """测试报告"""
    title: str
    version: str = "1.0"
    generated_at: str = ""
    summary: dict = field(default_factory=dict)
    sections: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class Reporter:
    """报告生成器"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.output_dir = self.config.get("output_dir", "data/harness/reports")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_test_report(
        self,
        test_results: list,
        evaluation_reports: list = None,
        trace_data: dict = None,
        title: str = "Hedera 测试报告",
    ) -> TestReport:
        """生成测试报告"""
        report = TestReport(
            title=title,
            generated_at=datetime.now().isoformat(),
        )

        report.summary = self._build_summary(test_results)
        report.sections.append(self._build_overview_section(test_results))
        report.sections.append(self._build_detail_section(test_results))

        if evaluation_reports:
            report.sections.append(self._build_evaluation_section(evaluation_reports))

        if trace_data:
            report.sections.append(self._build_trace_section(trace_data))

        report.sections.append(self._build_recommendations_section(test_results, evaluation_reports))

        return report

    def _build_summary(self, results: list) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r.status.value == "passed")
        failed = sum(1 for r in results if r.status.value == "failed")
        errors = sum(1 for r in results if r.status.value == "error")

        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "pass_rate": f"{passed / total * 100:.1f}%" if total > 0 else "N/A",
            "avg_latency_ms": sum(r.latency_ms for r in results) / total if total > 0 else 0,
        }

    def _build_overview_section(self, results: list) -> ReportSection:
        section = ReportSection(title="测试概览")

        categories = {}
        for r in results:
            cat = getattr(r, 'category', 'general')
            if cat not in categories:
                categories[cat] = {"total": 0, "passed": 0}
            categories[cat]["total"] += 1
            if r.status.value == "passed":
                categories[cat]["passed"] += 1

        content_lines = ["### 测试分类统计\n"]
        for cat, stats in categories.items():
            rate = stats["passed"] / stats["total"] * 100 if stats["total"] > 0 else 0
            content_lines.append(f"- **{cat}**: {stats['passed']}/{stats['total']} ({rate:.1f}%)")

        section.content = "\n".join(content_lines)
        section.metrics = categories
        return section

    def _build_detail_section(self, results: list) -> ReportSection:
        section = ReportSection(title="测试详情")

        content_lines = ["### 测试结果列表\n"]
        for r in results:
            status_icon = "✅" if r.status.value == "passed" else "❌" if r.status.value == "failed" else "⚠️"
            content_lines.append(f"#### {status_icon} {r.test_name}")
            content_lines.append(f"- **ID**: {r.test_id}")
            content_lines.append(f"- **状态**: {r.status.value}")
            content_lines.append(f"- **延迟**: {r.latency_ms:.0f}ms")

            if r.assertions:
                content_lines.append("- **断言**:")
                for a in r.assertions:
                    icon = "✅" if a.passed else "❌"
                    content_lines.append(f"  - {icon} {a.type}: {a.message}")

            if r.error_message:
                content_lines.append(f"- **错误**: {r.error_message}")

            content_lines.append("")

        section.content = "\n".join(content_lines)
        return section

    def _build_evaluation_section(self, reports: list) -> ReportSection:
        section = ReportSection(title="质量评估")

        if not reports:
            section.content = "无评估数据"
            return section

        overall_scores = [r.overall_score for r in reports]
        avg_score = sum(overall_scores) / len(overall_scores) if overall_scores else 0

        grades = {}
        for r in reports:
            grades[r.grade] = grades.get(r.grade, 0) + 1

        content_lines = [
            "### 评估摘要\n",
            f"- **平均分数**: {avg_score:.2f}",
            f"- **评估用例数**: {len(reports)}",
            "",
            "### 等级分布\n",
        ]
        for grade, count in sorted(grades.items()):
            content_lines.append(f"- **{grade}**: {count} 个")

        content_lines.append("\n### 指标详情\n")
        metric_totals = {}
        for r in reports:
            for m in r.metrics:
                if m.type.value not in metric_totals:
                    metric_totals[m.type.value] = {"scores": [], "weights": []}
                metric_totals[m.type.value]["scores"].append(m.score)
                metric_totals[m.type.value]["weights"].append(m.weight)

        for metric_name, data in metric_totals.items():
            avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
            content_lines.append(f"- **{metric_name}**: {avg:.2f}")

        section.content = "\n".join(content_lines)
        section.metrics = {
            "avg_score": avg_score,
            "grade_distribution": grades,
            "metric_breakdown": {k: sum(v["scores"]) / len(v["scores"]) for k, v in metric_totals.items()},
        }
        return section

    def _build_trace_section(self, trace_data: dict) -> ReportSection:
        section = ReportSection(title="追踪分析")

        if not trace_data:
            section.content = "无追踪数据"
            return section

        content_lines = [
            "### 追踪摘要\n",
            f"- **追踪 ID**: {trace_data.get('trace_id', 'N/A')}",
            f"- **总事件数**: {trace_data.get('total_events', 0)}",
            f"- **总耗时**: {trace_data.get('total_duration_ms', 0):.0f}ms",
            "",
            "### 事件分布\n",
        ]

        event_dist = trace_data.get("event_type_distribution", {})
        for event_type, count in event_dist.items():
            content_lines.append(f"- **{event_type}**: {count}")

        if trace_data.get("tool_calls"):
            content_lines.append("\n### 工具调用\n")
            for tool in trace_data["tool_calls"]:
                content_lines.append(f"- {tool}")

        if trace_data.get("errors"):
            content_lines.append("\n### 错误\n")
            for error in trace_data["errors"]:
                content_lines.append(f"- {error}")

        section.content = "\n".join(content_lines)
        return section

    def _build_recommendations_section(self, test_results: list, evaluation_reports: list = None) -> ReportSection:
        section = ReportSection(title="改进建议")

        recommendations = []

        failed_tests = [r for r in test_results if r.status.value == "failed"]
        if failed_tests:
            recommendations.append("### 测试失败分析\n")
            for r in failed_tests[:5]:
                recommendations.append(f"- **{r.test_name}**: {r.error_message or '断言失败'}")

        if evaluation_reports:
            low_scores = [r for r in evaluation_reports if r.overall_score < 0.7]
            if low_scores:
                recommendations.append("\n### 低分用例\n")
                for r in low_scores[:5]:
                    recommendations.append(f"- **{r.test_id}**: 分数 {r.overall_score:.2f}")
                    for rec in r.recommendations[:2]:
                        recommendations.append(f"  - {rec}")

        if not recommendations:
            recommendations.append("所有测试通过，无改进建议。")

        section.content = "\n".join(recommendations)
        return section

    def export_markdown(self, report: TestReport, path: str = None) -> str:
        """导出为 Markdown 格式"""
        if not path:
            path = os.path.join(self.output_dir, f"report_{int(time.time())}.md")

        lines = [
            f"# {report.title}",
            f"",
            f"**生成时间**: {report.generated_at}",
            f"**版本**: {report.version}",
            "",
            "---",
            "",
            "## 摘要",
            "",
        ]

        for key, value in report.summary.items():
            lines.append(f"- **{key}**: {value}")

        lines.append("")
        lines.append("---")

        for section in report.sections:
            lines.append("")
            lines.append(f"## {section.title}")
            lines.append("")
            if section.content:
                lines.append(section.content)
            lines.append("")

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return path

    def export_json(self, report: TestReport, path: str = None) -> str:
        """导出为 JSON 格式"""
        if not path:
            path = os.path.join(self.output_dir, f"report_{int(time.time())}.json")

        data = {
            "title": report.title,
            "version": report.version,
            "generated_at": report.generated_at,
            "summary": report.summary,
            "sections": [
                {
                    "title": s.title,
                    "content": s.content,
                    "metrics": s.metrics,
                }
                for s in report.sections
            ],
            "metadata": report.metadata,
        }

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return path

    def export_html(self, report: TestReport, path: str = None) -> str:
        """导出为 HTML 格式"""
        if not path:
            path = os.path.join(self.output_dir, f"report_{int(time.time())}.html")

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{report.title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
        .header {{ background: #2c3e50; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .card h3 {{ margin-top: 0; color: #2c3e50; }}
        .metric {{ font-size: 2em; font-weight: bold; color: #3498db; }}
        .passed {{ color: #27ae60; }}
        .failed {{ color: #e74c3c; }}
        .section {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
        .section h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 0.8em; }}
        .badge-passed {{ background: #d4edda; color: #155724; }}
        .badge-failed {{ background: #f8d7da; color: #721c24; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{report.title}</h1>
        <p>生成时间: {report.generated_at}</p>
    </div>

    <div class="summary">
        <div class="card">
            <h3>总测试数</h3>
            <div class="metric">{report.summary.get('total_tests', 0)}</div>
        </div>
        <div class="card">
            <h3>通过</h3>
            <div class="metric passed">{report.summary.get('passed', 0)}</div>
        </div>
        <div class="card">
            <h3>失败</h3>
            <div class="metric failed">{report.summary.get('failed', 0)}</div>
        </div>
        <div class="card">
            <h3>通过率</h3>
            <div class="metric">{report.summary.get('pass_rate', 'N/A')}</div>
        </div>
    </div>
"""

        for section in report.sections:
            html += f"""
    <div class="section">
        <h2>{section.title}</h2>
        <div>{self._markdown_to_html(section.content)}</div>
    </div>
"""

        html += """
</body>
</html>"""

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

        return path

    def _markdown_to_html(self, md: str) -> str:
        """简单 Markdown 转 HTML"""
        if not md:
            return ""

        html = md
        html = html.replace("### ", "<h3>").replace("\n<h3>", "\n<h3>")
        html = html.replace("#### ", "<h4>").replace("\n<h4>", "\n<h4>")

        lines = html.split("\n")
        result = []
        in_list = False

        for line in lines:
            if line.startswith("- "):
                if not in_list:
                    result.append("<ul>")
                    in_list = True
                result.append(f"<li>{line[2:]}</li>")
            else:
                if in_list:
                    result.append("</ul>")
                    in_list = False
                if line.startswith("  - "):
                    result.append(f"<ul><li>{line[4:]}</li></ul>")
                elif line.startswith("<h"):
                    result.append(line)
                else:
                    result.append(f"<p>{line}</p>")

        if in_list:
            result.append("</ul>")

        return "\n".join(result)
