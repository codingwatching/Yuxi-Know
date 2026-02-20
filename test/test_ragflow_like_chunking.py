from __future__ import annotations

import os
import sys

sys.path.append(os.getcwd())

from src.knowledge.chunking.ragflow_like.dispatcher import chunk_markdown
from src.knowledge.chunking.ragflow_like.nlp import bullets_category
from src.knowledge.chunking.ragflow_like.presets import (
    CHUNK_ENGINE_VERSION,
    get_chunk_preset_options,
    map_to_internal_parser_id,
    resolve_chunk_processing_params,
)


def test_general_maps_to_naive() -> None:
    assert map_to_internal_parser_id("general") == "naive"


def test_resolve_chunk_processing_params_priority() -> None:
    resolved = resolve_chunk_processing_params(
        kb_additional_params={
            "chunk_preset_id": "book",
            "chunk_parser_config": {"chunk_token_num": 300, "delimiter": "\\n"},
        },
        file_processing_params={
            "chunk_preset_id": "qa",
            "chunk_parser_config": {"delimiter": "###"},
        },
        request_params={
            "chunk_preset_id": "laws",
            "chunk_parser_config": {"chunk_token_num": 666},
            "chunk_size": 777,
        },
    )

    assert resolved["chunk_preset_id"] == "laws"
    assert resolved["chunk_engine_version"] == CHUNK_ENGINE_VERSION
    # legacy chunk_size 在当前实现里会映射为 chunk_token_num
    assert resolved["chunk_parser_config"]["chunk_token_num"] == 777
    assert resolved["chunk_parser_config"]["delimiter"] == "###"


def test_qa_chunking_from_markdown_headings() -> None:
    content = """
# 问题一
这是答案一。

## 子问题
这是答案二。
""".strip()

    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_1",
        filename="faq.md",
        processing_params={"chunk_preset_id": "qa", "chunk_parser_config": {}},
    )

    assert len(chunks) >= 1
    assert "问题：" in chunks[0]["content"]
    assert "回答：" in chunks[0]["content"]


def test_book_chunking_hierarchical_merge() -> None:
    content = """
第一章 总则
第一节 适用范围
本规范适用于测试场景。
第二节 基本原则
应当遵循最小改动原则。
""".strip()

    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_2",
        filename="book.txt",
        processing_params={"chunk_preset_id": "book", "chunk_parser_config": {"chunk_token_num": 256}},
    )

    assert len(chunks) >= 1
    assert any("第一章" in ck["content"] for ck in chunks)


def test_markdown_heading_has_higher_weight_in_bullet_category() -> None:
    sections = [
        "# 3.2 个人所得项目及计税、申报方式概括",
        "一、关于季节工、临时工等费用税前扣除问题，以下规定继续执行。",
        "二、根据现行规定，补贴收入应并入工资薪金所得。",
        "（一）从超出国家规定比例支付的补贴，不属于免税福利费。",
    ]

    # 命中 markdown 标题模式（BULLET_PATTERN 下标 4）时，应该优先选中该组。
    assert bullets_category(sections) == 4


def test_mid_sentence_bullet_marker_should_not_be_treated_as_heading() -> None:
    sections = [
        "根据前述规则：一、这里是句中枚举，不是章节标题，不能被当成层级。",
        "延续上文：（二）这里同样是正文中的枚举表达，不是独立标题。",
        "## 3.4 交通补贴的个税处理",
    ]
    assert bullets_category(sections) == 4


def test_chunk_preset_options_include_description() -> None:
    options = get_chunk_preset_options()
    assert len(options) == 4
    assert all(isinstance(option.get("description"), str) and option["description"] for option in options)
