"""GAIA 评估文件处理模块

将 GAIA 数据集中的附件文件转换为 Agent 可识别的 attachments + state files 格式。
"""

from __future__ import annotations

import base64
import mimetypes
import os
from datetime import datetime

from src.utils import logger


# 支持直接读取内容的文本类文件扩展名
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl",
    ".xml", ".html", ".htm", ".yaml", ".yml", ".log",
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h",
    ".rb", ".go", ".rs", ".sh", ".bat", ".sql",
    ".ini", ".cfg", ".conf", ".toml",
}

# 支持用 PDF 解析的扩展名
PDF_EXTENSIONS = {".pdf"}

# 支持用 pandas 等读取的表格扩展名
SPREADSHEET_EXTENSIONS = {".xlsx", ".xls"}

# 图片类扩展名（用于多模态消息）
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _read_text_file(file_path: str) -> str | None:
    """读取纯文本文件"""
    encodings = ["utf-8", "latin-1", "gbk"]
    for enc in encodings:
        try:
            with open(file_path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    return None


def _read_pdf_file(file_path: str) -> str | None:
    """解析 PDF 文件为文本"""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("PyMuPDF (fitz) 未安装，无法解析 PDF。请安装: pip install PyMuPDF")
        return None
    except Exception as e:
        logger.warning(f"PDF 解析失败 {file_path}: {e}")
        return None


def _read_spreadsheet_file(file_path: str) -> str | None:
    """读取 Excel 文件并转为 CSV 文本"""
    try:
        import pandas as pd

        df = pd.read_excel(file_path)
        return df.to_csv(index=False)
    except ImportError:
        logger.warning("pandas/openpyxl 未安装，无法解析 Excel。请安装: pip install pandas openpyxl")
        return None
    except Exception as e:
        logger.warning(f"Excel 解析失败 {file_path}: {e}")
        return None


def _read_image_as_base64(file_path: str) -> str | None:
    """读取图片为 base64"""
    try:
        with open(file_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        logger.warning(f"图片读取失败 {file_path}: {e}")
        return None


def read_file_content(file_path: str) -> str | None:
    """根据文件类型读取内容，返回文本"""
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"文件不存在: {file_path}")
        return None

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext in TEXT_EXTENSIONS:
        return _read_text_file(file_path)
    elif ext in PDF_EXTENSIONS:
        return _read_pdf_file(file_path)
    elif ext in SPREADSHEET_EXTENSIONS:
        return _read_spreadsheet_file(file_path)
    else:
        # 尝试作为文本读取
        content = _read_text_file(file_path)
        if content:
            return content
        logger.warning(f"不支持的文件类型: {ext} ({file_path})")
        return None


def build_attachments_and_files(
    file_path: str,
    file_name: str | None = None,
) -> tuple[list[dict], dict]:
    """将文件转换为 Agent 的 attachments 和 state files 格式

    返回:
        (attachments, files) 元组：
        - attachments: 附件元数据列表，用于 AttachmentMiddleware
        - files: StateBackend 格式的文件字典，用于 read_file 工具
    """
    if not file_path or not os.path.exists(file_path):
        return [], {}

    if not file_name:
        file_name = os.path.basename(file_path)

    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    # 图片使用多模态消息，不走 attachment 机制
    if ext in IMAGE_EXTENSIONS:
        return [], {}

    content = read_file_content(file_path)
    if not content:
        return [], {}

    now = datetime.utcnow().isoformat() + "+00:00"
    virtual_path = f"/attachments/{file_name}"

    # 构建 attachment 元数据
    attachment = {
        "file_name": file_name,
        "file_path": virtual_path,
        "status": "parsed",
        "markdown": content,
        "uploaded_at": now,
        "truncated": False,
    }

    # 构建 state files（与 _build_state_files 格式一致）
    content_lines = content.split("\n")
    files = {
        virtual_path: {
            "content": content_lines,
            "created_at": now,
            "modified_at": now,
        }
    }

    return [attachment], files


def build_image_message_content(file_path: str, question: str) -> list[dict] | None:
    """为图片文件构建多模态消息内容

    返回 HumanMessage 的 content（多模态格式），或 None 如果不是图片。
    """
    if not file_path or not os.path.exists(file_path):
        return None

    _, ext = os.path.splitext(file_path)
    if ext.lower() not in IMAGE_EXTENSIONS:
        return None

    base64_data = _read_image_as_base64(file_path)
    if not base64_data:
        return None

    mime_type = mimetypes.guess_type(file_path)[0] or "image/jpeg"

    return [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}},
    ]
