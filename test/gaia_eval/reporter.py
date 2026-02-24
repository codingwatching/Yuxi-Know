"""GAIA 评估报告生成模块

输出终端彩色表格和 JSON 详细报告。
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .config import EvalConfig
from .runner import EvalResult


class GaiaReporter:
    """评估报告生成器"""

    def __init__(self, config: EvalConfig, results: list[EvalResult]):
        self.config = config
        self.results = results

    def _compute_stats(self) -> dict:
        """计算统计数据"""
        total = len(self.results)
        correct = sum(1 for r in self.results if r.is_correct)
        errors = sum(1 for r in self.results if r.error is not None)

        # 按 Level 分组统计
        by_level: dict[int, dict] = defaultdict(lambda: {"total": 0, "correct": 0, "errors": 0})
        for r in self.results:
            by_level[r.level]["total"] += 1
            if r.is_correct:
                by_level[r.level]["correct"] += 1
            if r.error:
                by_level[r.level]["errors"] += 1

        # 耗时统计
        durations = [r.duration_seconds for r in self.results if not r.error]
        avg_duration = sum(durations) / len(durations) if durations else 0
        max_duration = max(durations) if durations else 0
        min_duration = min(durations) if durations else 0

        return {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total * 100, 2) if total > 0 else 0,
            "errors": errors,
            "by_level": {
                level: {
                    "total": stats["total"],
                    "correct": stats["correct"],
                    "accuracy": round(stats["correct"] / stats["total"] * 100, 2) if stats["total"] > 0 else 0,
                    "errors": stats["errors"],
                }
                for level, stats in sorted(by_level.items())
            },
            "duration": {
                "avg": round(avg_duration, 2),
                "max": round(max_duration, 2),
                "min": round(min_duration, 2),
                "total": round(sum(durations), 2),
            },
        }

    def print_report(self):
        """在终端输出彩色报告"""
        from rich.console import Console
        from rich.table import Table

        console = Console()
        stats = self._compute_stats()

        # 标题
        console.print("\n[bold cyan]═══ GAIA 评估报告 ═══[/bold cyan]\n")

        # 总体统计
        accuracy_color = "green" if stats["accuracy"] >= 50 else ("yellow" if stats["accuracy"] >= 25 else "red")
        console.print(f"  Agent:     [bold]{self.config.agent_id}[/bold]")
        if self.config.agent_config_id:
            console.print(f"  配置ID:    [bold]{self.config.agent_config_id}[/bold]")
        console.print(f"  总题数:    {stats['total']}")
        console.print(f"  正确数:    {stats['correct']}")
        console.print(f"  错误数:    {stats['errors']}")
        console.print(f"  准确率:    [{accuracy_color}]{stats['accuracy']}%[/{accuracy_color}]")
        console.print()

        # 按 Level 统计表
        level_table = Table(title="按 Level 统计")
        level_table.add_column("Level", style="bold")
        level_table.add_column("总数", justify="right")
        level_table.add_column("正确", justify="right")
        level_table.add_column("准确率", justify="right")
        level_table.add_column("错误", justify="right")

        for level, level_stats in stats["by_level"].items():
            acc_color = "green" if level_stats["accuracy"] >= 50 else (
                "yellow" if level_stats["accuracy"] >= 25 else "red"
            )
            level_table.add_row(
                f"Level {level}",
                str(level_stats["total"]),
                str(level_stats["correct"]),
                f"[{acc_color}]{level_stats['accuracy']}%[/{acc_color}]",
                str(level_stats["errors"]),
            )

        console.print(level_table)
        console.print()

        # 耗时统计
        console.print("[bold]耗时统计:[/bold]")
        console.print(f"  平均: {stats['duration']['avg']}s")
        console.print(f"  最大: {stats['duration']['max']}s")
        console.print(f"  最小: {stats['duration']['min']}s")
        console.print(f"  总计: {stats['duration']['total']}s")
        console.print()

        # 错误样本
        error_results = [r for r in self.results if r.error]
        if error_results:
            console.print(f"[bold red]错误样本 ({len(error_results)} 条):[/bold red]")
            for r in error_results[:5]:
                console.print(f"  • [{r.task_id[:8]}] L{r.level}: {r.error}")
            if len(error_results) > 5:
                console.print(f"  ... 还有 {len(error_results) - 5} 条错误")
            console.print()

    def save_json_report(self) -> Path:
        """保存 JSON 详细报告"""
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        stats = self._compute_stats()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = self.config.output_dir / f"gaia_eval_{timestamp}.json"

        report = {
            "metadata": {
                "timestamp": timestamp,
                "agent_id": self.config.agent_id,
                "agent_config_id": self.config.agent_config_id,
                "level": self.config.level,
                "split": self.config.split,
                "timeout": self.config.timeout,
            },
            "summary": stats,
            "results": [
                {
                    "task_id": r.task_id,
                    "level": r.level,
                    "question": r.question,
                    "gold_answer": r.gold_answer,
                    "predicted_answer": r.predicted_answer,
                    "is_correct": r.is_correct,
                    "error": r.error,
                    "duration_seconds": r.duration_seconds,
                }
                for r in self.results
            ],
        }

        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path
