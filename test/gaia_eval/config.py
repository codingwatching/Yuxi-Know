"""GAIA 评估配置管理模块"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalConfig:
    """GAIA 评估配置

    配置优先级：CLI 参数 > 环境变量 > 默认值
    当指定 agent_config_id 时，会从数据库加载预设配置（model/tools/knowledges/system_prompt 等）
    """

    # Agent 相关
    agent_id: str = "ChatbotAgent"
    agent_config_id: int | None = None  # 从数据库加载预设配置

    # 备选配置（当未指定 agent_config_id 时使用）
    model: str | None = None
    system_prompt: str | None = None
    tools: list[dict] | None = None
    knowledges: list[str] | None = None

    # 数据集相关
    level: str = "all"  # "1", "2", "3", "all"
    split: str = "validation"  # "validation" or "test"
    max_samples: int | None = None  # 限制评估样本数（调试用）

    # 运行控制
    timeout: int = 300  # 单题超时，秒
    concurrency: int = 1  # 并发评估数

    # 输出相关
    output_dir: Path = field(default_factory=lambda: Path("eval_results"))

    def get_dataset_configs(self) -> list[str]:
        """根据 level 获取 HuggingFace dataset config 名称列表"""
        if self.level == "all":
            return ["2023_level1", "2023_level2", "2023_level3"]
        return [f"2023_level{self.level}"]

    def build_agent_config(self) -> dict:
        """构建不使用 agent_config_id 时的 agent_config 字典

        当未指定 agent_config_id 时，从 CLI 参数组装配置。
        """
        config = {}
        if self.model:
            config["model"] = self.model
        if self.system_prompt:
            config["system_prompt"] = self.system_prompt
        if self.tools is not None:
            config["tools"] = self.tools
        if self.knowledges is not None:
            config["knowledges"] = self.knowledges
        return config
