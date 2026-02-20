from __future__ import annotations

import re
from typing import Any

from src.knowledge.chunking.ragflow_like import nlp


def _unescape_delimiter(delimiter: str) -> str:
    return delimiter.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace("\\\\", "\\")


def _iter_lines(markdown_content: str) -> list[str]:
    return [line.strip() for line in (markdown_content or "").splitlines() if line.strip()]


def _docx_heading_tree(markdown_content: str) -> list[str]:
    lines: list[tuple[int, str]] = []
    level_set: set[int] = set()

    for raw in (markdown_content or "").splitlines():
        text = raw.strip()
        if not text:
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", text)
        if heading_match:
            level = len(heading_match.group(1))
            value = heading_match.group(2).strip()
        else:
            level = 99
            value = text

        if not value:
            continue

        lines.append((level, value))
        level_set.add(level)

    if not lines:
        return []

    sorted_levels = sorted(level_set)
    h2_level = sorted_levels[1] if len(sorted_levels) > 1 else 1
    h2_level = sorted_levels[-2] if h2_level == sorted_levels[-1] and len(sorted_levels) > 2 else h2_level

    root = nlp.Node(level=0, depth=h2_level, texts=[])
    root.build_tree(lines)
    return [element for element in root.get_tree() if element]


def chunk_markdown(filename: str, markdown_content: str, parser_config: dict[str, Any] | None = None) -> list[str]:
    parser_config = parser_config or {}

    delimiter = _unescape_delimiter(str(parser_config.get("delimiter", "\n") or "\n"))
    chunk_token_num = int(parser_config.get("chunk_token_num", 512) or 512)
    overlapped_percent = int(parser_config.get("overlapped_percent", 0) or 0)

    if re.search(r"\.docx$", filename or "", re.IGNORECASE):
        chunks = _docx_heading_tree(markdown_content)
        if chunks:
            return chunks

    sections = _iter_lines(markdown_content)
    if not sections:
        return []

    eng = nlp.is_english(sections)
    nlp.remove_contents_table(sections, eng=eng)

    typed_sections = [(s, "") for s in sections]
    nlp.make_colon_as_title(typed_sections)

    bull = nlp.bullets_category([s for s, _ in typed_sections])
    merged = nlp.tree_merge(bull, typed_sections, depth=2)

    if merged:
        return merged

    return nlp.naive_merge(
        typed_sections,
        chunk_token_num=chunk_token_num,
        delimiter=delimiter,
        overlapped_percent=overlapped_percent,
    )
