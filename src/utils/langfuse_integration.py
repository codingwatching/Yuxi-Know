"""
Langfuse 集成模块

提供 Langfuse 的初始化和回调处理器获取功能。
仅当环境变量 LANGFUSE_SECRET_KEY 和 LANGFUSE_PUBLIC_KEY 存在时启用。
"""

import os
from functools import lru_cache

from src.utils.logging_config import logger


def is_langfuse_enabled() -> bool:
    """检查 Langfuse 是否已配置"""
    return bool(
        os.getenv("LANGFUSE_SECRET_KEY")
        and os.getenv("LANGFUSE_PUBLIC_KEY")
    )


@lru_cache(maxsize=1)
def get_langfuse_callback():
    """获取 Langfuse LangChain CallbackHandler（单例）

    Returns:
        CallbackHandler 实例，若 Langfuse 未配置则返回 None
    """
    if not is_langfuse_enabled():
        return None
    try:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler()
        logger.info("Langfuse CallbackHandler 初始化成功")
        return handler
    except Exception as e:
        logger.warning(f"Langfuse CallbackHandler 初始化失败: {e}")
        return None
