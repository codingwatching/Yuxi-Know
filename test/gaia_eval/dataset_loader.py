"""GAIA 数据集加载器

支持两种模式：
  1. 流式模式（默认）：直接 streaming 拉取 metadata，无需完整下载，适合快速测试
  2. 完整模式：snapshot_download 后加载，附件文件可本地读取

需要设置 HF_TOKEN 环境变量，并在 HuggingFace 上同意数据集使用条款。
"""

import os
from dataclasses import dataclass

from .config import EvalConfig


@dataclass
class GaiaTask:
    """单条 GAIA 评估任务"""

    task_id: str
    question: str
    level: int
    final_answer: str
    file_name: str | None = None
    file_path: str | None = None  # 流式模式下为 None（无本地文件）
    annotator_metadata: dict | None = None


def _get_token() -> str | None:
    """获取 HF_TOKEN，支持从环境变量或 .env 文件读取"""
    token = os.environ.get("HF_TOKEN")
    if not token:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            token = os.environ.get("HF_TOKEN")
        except ImportError:
            pass
    return token


class GaiaDatasetLoader:
    """GAIA 数据集加载器"""

    REPO_ID = "gaia-benchmark/GAIA"

    def __init__(self, config: EvalConfig):
        self.config = config
        self._data_dir: str | None = None  # 完整下载后的本地路径

    def load_tasks(self) -> list[GaiaTask]:
        """加载并返回 GaiaTask 列表

        当 max_samples 较小时，自动使用流式加载避免完整下载；
        否则使用 snapshot_download 完整下载（支持附件文件读取）。
        """
        # 小样本时用流式加载，避免下载完整数据集
        small_sample = self.config.max_samples and self.config.max_samples <= 50
        if small_sample:
            return self._load_streaming()
        else:
            return self._load_full()

    def _load_streaming(self) -> list[GaiaTask]:
        """流式加载：直接从 HuggingFace 流式拉取，附件文件按需单独下载"""
        from datasets import load_dataset
        from huggingface_hub import hf_hub_download

        token = _get_token()
        if not token:
            raise RuntimeError(
                "未设置 HF_TOKEN 环境变量。请在 .env 中添加 HF_TOKEN=hf_xxx"
            )

        dataset_configs = self.config.get_dataset_configs()
        tasks: list[GaiaTask] = []

        for ds_config in dataset_configs:
            dataset = load_dataset(
                self.REPO_ID,
                ds_config,
                split=self.config.split,
                streaming=True,
                token=token,
            )

            for example in dataset:
                file_name = example.get("file_name") or None
                file_path = None

                # 按需下载单个附件文件（只下载当前任务的文件，不下载整个数据集）
                if file_name:
                    repo_file_path = f"2023/{self.config.split}/{file_name}"
                    try:
                        file_path = hf_hub_download(
                            repo_id=self.REPO_ID,
                            repo_type="dataset",
                            filename=repo_file_path,
                            token=token,
                        )
                    except Exception as e:
                        import warnings
                        warnings.warn(f"附件下载失败 {file_name}: {e}")

                task = GaiaTask(
                    task_id=example["task_id"],
                    question=example["Question"],
                    level=int(example["Level"]),
                    final_answer=example.get("Final answer", ""),
                    file_name=file_name,
                    file_path=file_path,
                    annotator_metadata=example.get("Annotator Metadata"),
                )
                tasks.append(task)

                if self.config.max_samples and len(tasks) >= self.config.max_samples:
                    return tasks

        return tasks

    def _load_full(self) -> list[GaiaTask]:
        """完整下载：先 snapshot_download，再加载（附件文件可本地读取）"""
        from datasets import load_dataset
        from huggingface_hub import snapshot_download

        token = _get_token()
        if not token:
            raise RuntimeError(
                "未设置 HF_TOKEN 环境变量。请在 .env 中添加 HF_TOKEN=hf_xxx"
            )

        if not self._data_dir:
            self._data_dir = snapshot_download(
                repo_id=self.REPO_ID,
                repo_type="dataset",
                token=token,
            )

        dataset_configs = self.config.get_dataset_configs()
        tasks: list[GaiaTask] = []

        for ds_config in dataset_configs:
            dataset = load_dataset(self._data_dir, ds_config, split=self.config.split)

            for example in dataset:
                file_path = example.get("file_path")
                if file_path:
                    file_path = os.path.join(self._data_dir, file_path)

                task = GaiaTask(
                    task_id=example["task_id"],
                    question=example["Question"],
                    level=int(example["Level"]),
                    final_answer=example.get("Final answer", ""),
                    file_name=example.get("file_name") or None,
                    file_path=file_path,
                    annotator_metadata=example.get("Annotator Metadata"),
                )
                tasks.append(task)

        if self.config.max_samples and len(tasks) > self.config.max_samples:
            tasks = tasks[: self.config.max_samples]

        return tasks
