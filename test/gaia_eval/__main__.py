"""GAIA 离线评估 CLI 入口

用法:
    python -m test.gaia_eval                                   # 评估全部级别
    python -m test.gaia_eval --level 1                         # 只评估 Level 1
    python -m test.gaia_eval --level 1 --max-samples 5         # 限制 5 条（调试）
    python -m test.gaia_eval --agent-config-id 3               # 使用数据库预设配置
    python -m test.gaia_eval --model deepseek-chat --level 1   # 指定模型
    python -m test.gaia_eval --output-dir ./my_results         # 自定义输出目录
"""

import argparse
import asyncio
import sys

from .config import EvalConfig
from .dataset_loader import GaiaDatasetLoader
from .reporter import GaiaReporter
from .runner import GaiaEvalRunner


def parse_args() -> EvalConfig:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="GAIA 离线评估 - 评估 Yuxi-Know Agent 系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--agent-id", default="ChatbotAgent", help="Agent ID（默认: ChatbotAgent）")
    parser.add_argument("--agent-config-id", type=int, default=None, help="Agent 预设配置 ID，从数据库加载")
    parser.add_argument("--model", default=None, help="模型名称（当未指定 agent-config-id 时使用）")
    parser.add_argument("--level", default="all", choices=["1", "2", "3", "all"], help="评估级别（默认: all）")
    parser.add_argument("--split", default="validation", choices=["validation", "test"], help="数据集划分（默认: validation）")
    parser.add_argument("--max-samples", type=int, default=None, help="最大评估样本数（调试用）")
    parser.add_argument("--timeout", type=int, default=300, help="单题超时，秒（默认: 300）")
    parser.add_argument("--concurrency", type=int, default=1, help="并发评估数（默认: 1）")
    parser.add_argument("--output-dir", default="eval_results", help="结果输出目录（默认: eval_results）")

    args = parser.parse_args()

    from pathlib import Path

    return EvalConfig(
        agent_id=args.agent_id,
        agent_config_id=args.agent_config_id,
        model=args.model,
        level=args.level,
        split=args.split,
        max_samples=args.max_samples,
        timeout=args.timeout,
        concurrency=args.concurrency,
        output_dir=Path(args.output_dir),
    )


async def main():
    """主流程"""
    from rich.console import Console

    console = Console()
    config = parse_args()

    # 1. 显示配置信息
    console.print("\n[bold cyan]═══ GAIA 离线评估 ═══[/bold cyan]")
    console.print(f"  Agent:       {config.agent_id}")
    if config.agent_config_id:
        console.print(f"  配置ID:      {config.agent_config_id}")
    if config.model:
        console.print(f"  模型:        {config.model}")
    console.print(f"  级别:        {config.level}")
    console.print(f"  数据集:      {config.split}")
    if config.max_samples:
        console.print(f"  样本限制:    {config.max_samples}")
    console.print(f"  超时:        {config.timeout}s")
    console.print(f"  并发:        {config.concurrency}")
    console.print(f"  输出目录:    {config.output_dir}")
    console.print()

    # 2. 加载数据集
    console.print("[bold]正在加载 GAIA 数据集...[/bold]")
    try:
        loader = GaiaDatasetLoader(config)
        tasks = loader.load_tasks()
    except Exception as e:
        console.print(f"[red]数据集加载失败: {e}[/red]")
        console.print("[dim]请确保已设置 HF_TOKEN 并同意了数据集使用条款[/dim]")
        sys.exit(1)

    console.print(f"  已加载 {len(tasks)} 条评估任务\n")

    if not tasks:
        console.print("[yellow]没有可评估的任务[/yellow]")
        sys.exit(0)

    # 3. 执行评估
    console.print("[bold]开始评估...[/bold]\n")
    runner = GaiaEvalRunner(config)
    results = await runner.run(tasks)

    # 4. 生成报告
    reporter = GaiaReporter(config, results)
    reporter.print_report()

    report_path = reporter.save_json_report()
    console.print(f"[green]详细报告已保存: {report_path}[/green]\n")


if __name__ == "__main__":
    asyncio.run(main())
