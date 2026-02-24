"""GAIA 评估运行器

核心评估逻辑：加载 agent、执行评估、收集结果。
"""

import asyncio
import time
import uuid
from dataclasses import dataclass

from tqdm import tqdm

from .config import EvalConfig
from .dataset_loader import GaiaTask
from .scorer import GaiaScorer


@dataclass
class EvalResult:
    """单条评估结果"""

    task_id: str
    level: int
    question: str
    gold_answer: str
    predicted_answer: str
    is_correct: bool
    error: str | None = None
    duration_seconds: float = 0.0


class GaiaEvalRunner:
    """GAIA 评估运行器

    通过直接调用 BaseAgent.invoke_messages() 执行评估，
    无需启动 Web 服务。
    """

    def __init__(self, config: EvalConfig):
        self.config = config
        self._agent = None
        self._agent_config: dict = {}

    async def _init_agent(self):
        """初始化 Agent 实例并加载预设配置"""
        from src.agents import agent_manager

        self._agent = agent_manager.get_agent(self.config.agent_id)

        # 如果指定了 agent_config_id，从数据库加载预设配置
        if self.config.agent_config_id is not None:
            await self._load_agent_config_from_db()
        else:
            # 使用 CLI 参数组装配置
            self._agent_config = self.config.build_agent_config()

    async def _load_agent_config_from_db(self):
        """从数据库加载 agent 预设配置"""
        from src.repositories.agent_config_repository import AgentConfigRepository
        from src.storage.postgres.manager import pg_manager

        # 评估脚本独立运行时，pg_manager 和 mcp_service 未经过 FastAPI 启动事件初始化，需手动初始化
        if not pg_manager._initialized:
            pg_manager.initialize()
        
        from src.services.mcp_service import init_mcp_servers
        await init_mcp_servers()

        async with pg_manager.get_async_session_context() as db:
            repo = AgentConfigRepository(db)
            config_item = await repo.get_by_id(self.config.agent_config_id)

            if config_item is None:
                raise ValueError(f"Agent 配置 ID {self.config.agent_config_id} 不存在")

            # 与线上逻辑保持一致：从 config_json.context 中提取配置
            self._agent_config = (config_item.config_json or {}).get("context", {})

    def _extract_answer(self, result: dict) -> str:
        """从 agent 返回结果中提取最终答案

        Agent 返回格式为 { "messages": [...] }，取最后一条 AI 消息的内容。
        """
        messages = result.get("messages", [])
        if not messages:
            return ""

        # 从后往前找第一条 AI 消息
        for msg in reversed(messages):
            msg_type = getattr(msg, "type", None)
            if msg_type == "ai":
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    return self._parse_final_answer(content)

        return ""

    @staticmethod
    def _parse_final_answer(content: str) -> str:
        """尝试从 AI 回复中解析出最终答案

        如果回复中包含 "FINAL ANSWER:" 标记，则提取标记后面的内容。
        否则返回完整回复。
        """
        # 常见答案标记格式
        markers = [
            "FINAL ANSWER:",
            "Final Answer:",
            "final answer:",
            "最终答案：",
            "最终答案:",
            "答案：",
            "答案:",
        ]
        for marker in markers:
            if marker in content:
                answer = content.split(marker, 1)[1].strip()
                # 取第一行（去掉后续的解释）
                first_line = answer.split("\n")[0].strip()
                return first_line

        # 如果只有一行，直接返回
        lines = [ln.strip() for ln in content.strip().split("\n") if ln.strip()]
        if len(lines) == 1:
            return lines[0]

        # 多行回复，返回最后一行（通常是最终答案）
        return lines[-1] if lines else content.strip()

    async def _run_single_task(self, task: GaiaTask) -> EvalResult:
        """执行单条评估任务"""
        start_time = time.time()
        predicted_answer = ""
        error = None

        try:
            from langchain.messages import HumanMessage

            from .file_handler import build_attachments_and_files, build_image_message_content

            # 构建系统提示词
            gaia_system_suffix = (
                "\n\nIMPORTANT: When you have found the answer, "
                "state it clearly on a single line prefixed with 'FINAL ANSWER: '. "
                "Keep the answer as concise as possible - just the answer itself, "
                "no extra explanation."
            )

            input_context = {
                "user_id": "gaia_eval",
                "thread_id": str(uuid.uuid4()),
                "agent_config": {
                    **self._agent_config,
                    "system_prompt": (
                        self._agent_config.get("system_prompt", "You are a helpful assistant.")
                        + gaia_system_suffix
                    ),
                },
            }

            # 处理附件文件
            attachments: list[dict] = []
            files: dict = {}
            image_content: list[dict] | None = None

            if task.file_path:
                # 尝试构建图片多模态消息
                image_content = build_image_message_content(task.file_path, task.question)

                if not image_content:
                    # 非图片文件：通过 attachments + files 注入 state
                    attachments, files = build_attachments_and_files(
                        task.file_path, task.file_name
                    )

            # 构建消息
            if image_content:
                # 图片：使用多模态 HumanMessage
                messages = [HumanMessage(content=image_content)]
            else:
                messages = [HumanMessage(content=task.question)]

            # 构建 graph 输入（包含 attachments 和 files）
            graph_input = {"messages": messages}
            if attachments:
                graph_input["attachments"] = attachments
            if files:
                graph_input["files"] = files

            # 直接调用 graph.ainvoke 以传递完整的初始 state
            graph = await self._agent.get_graph()
            context = self._agent.context_schema()
            agent_config = input_context.get("agent_config")
            if isinstance(agent_config, dict):
                context.update(agent_config)
            context.update(input_context)

            invoke_config = {
                "configurable": {
                    "thread_id": context.thread_id,
                    "user_id": context.user_id,
                },
                "recursion_limit": 100,
            }

            # 设置超时
            result = await asyncio.wait_for(
                graph.ainvoke(graph_input, context=context, config=invoke_config),
                timeout=self.config.timeout,
            )

            predicted_answer = self._extract_answer(result)

        except TimeoutError:
            error = f"Timeout after {self.config.timeout}s"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

        duration = time.time() - start_time
        is_correct = GaiaScorer.score(predicted_answer, task.final_answer) if not error else False

        return EvalResult(
            task_id=task.task_id,
            level=task.level,
            question=task.question,
            gold_answer=task.final_answer,
            predicted_answer=predicted_answer,
            is_correct=is_correct,
            error=error,
            duration_seconds=round(duration, 2),
        )

    async def run(self, tasks: list[GaiaTask]) -> list[EvalResult]:
        """执行批量评估

        Args:
            tasks: 待评估的 GaiaTask 列表

        Returns:
            评估结果列表
        """
        await self._init_agent()

        results: list[EvalResult] = []

        if self.config.concurrency <= 1:
            # 串行执行
            for task in tqdm(tasks, desc="评估进度", unit="题"):
                result = await self._run_single_task(task)
                results.append(result)
                status = "✓" if result.is_correct else ("✗" if not result.error else "⚠")
                tqdm.write(
                    f"  {status} [{result.task_id[:8]}] L{result.level} "
                    f"| 预测: {result.predicted_answer[:50]!r} "
                    f"| 标准: {result.gold_answer[:50]!r} "
                    f"| {result.duration_seconds:.1f}s"
                )
        else:
            # 并发执行（使用信号量控制并发度）
            semaphore = asyncio.Semaphore(self.config.concurrency)
            pbar = tqdm(total=len(tasks), desc="评估进度", unit="题")

            async def bounded_run(task: GaiaTask) -> EvalResult:
                async with semaphore:
                    result = await self._run_single_task(task)
                    pbar.update(1)
                    return result

            results = await asyncio.gather(*[bounded_run(t) for t in tasks])
            pbar.close()

        return results
