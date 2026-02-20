from __future__ import annotations

import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from src import config as sys_config
from src.repositories.skill_repository import SkillRepository
from src.storage.postgres.manager import pg_manager
from src.storage.postgres.models_business import Skill
from src.utils.logging_config import logger

SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

TEXT_FILE_EXTENSIONS = {
    ".md",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
    ".env",
    ".csv",
    ".tsv",
    ".rst",
    ".ipynb",
    ".vue",
    ".jsx",
    ".tsx",
}

_skill_options_cache: list[dict[str, str]] = []
_skill_prompt_metadata_cache: dict[str, dict[str, str]] = {}


def get_skills_root_dir() -> Path:
    root = Path(sys_config.save_dir) / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_skill_options() -> list[dict[str, str]]:
    """返回技能选项缓存（用于 BaseContext configurable options）。"""
    return list(_skill_options_cache)


def get_skill_prompt_metadata_by_slugs(slugs: list[str]) -> list[dict[str, str]]:
    """按 slug 顺序返回 skills prompt 元数据（仅缓存，无 IO）。"""
    if not slugs:
        return []

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)

        item = _skill_prompt_metadata_cache.get(slug)
        if not item:
            logger.debug(f"Skill slug not found in cache, skip prompt metadata: {slug}")
            continue

        result.append(dict(item))

    return result


def _set_skill_options_cache(items: list[Skill]) -> None:
    global _skill_options_cache, _skill_prompt_metadata_cache
    _skill_options_cache = [
        {
            "id": item.slug,
            "name": item.name,
            "description": item.description,
        }
        for item in items
    ]
    _skill_prompt_metadata_cache = {
        item.slug: {
            "name": item.name,
            "description": item.description,
            "path": f"/skills/{item.slug}/SKILL.md",
        }
        for item in items
    }


async def init_skills_cache() -> None:
    """启动时加载技能缓存，避免每次构建 configurable_items 触发 DB IO。"""
    try:
        async with pg_manager.get_async_session_context() as session:
            repo = SkillRepository(session)
            items = await repo.list_all()
            _set_skill_options_cache(items)
            logger.info(f"Loaded skills cache with {len(items)} items")
    except Exception as e:
        logger.warning(f"Failed to initialize skills cache: {e}")


async def list_skills(db: AsyncSession) -> list[Skill]:
    repo = SkillRepository(db)
    items = await repo.list_all()
    _set_skill_options_cache(items)
    return items


def _validate_skill_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("SKILL.md frontmatter 缺少 name")
    if len(name) > 128:
        raise ValueError("skill name 长度不能超过 128")
    if not SKILL_NAME_PATTERN.match(name):
        raise ValueError("skill name 必须是小写字母/数字/短横线，且不能连续短横线")
    return name


def _parse_skill_markdown(content: str) -> tuple[str, str, dict[str, Any]]:
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise ValueError("SKILL.md 缺少有效 frontmatter（--- ... ---）")

    frontmatter_raw = match.group(1)
    try:
        data = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        raise ValueError(f"SKILL.md frontmatter YAML 解析失败: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter 必须是对象")

    name = _validate_skill_name(str(data.get("name", "")))
    description = str(data.get("description", "")).strip()
    if not description:
        raise ValueError("SKILL.md frontmatter 缺少 description")

    return name, description, data


def _rewrite_frontmatter_name(content: str, new_name: str) -> str:
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise ValueError("SKILL.md 缺少有效 frontmatter（--- ... ---）")

    frontmatter_raw = match.group(1)
    body = content[match.end() :]
    data = yaml.safe_load(frontmatter_raw)
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter 必须是对象")
    data["name"] = new_name
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n{body}"


def _validate_zip_paths(zip_file: zipfile.ZipFile) -> None:
    for name in zip_file.namelist():
        pure = PurePosixPath(name)
        if pure.is_absolute():
            raise ValueError(f"ZIP 包含不安全绝对路径: {name}")
        if ".." in pure.parts:
            raise ValueError(f"ZIP 包含路径穿越片段: {name}")


async def _generate_available_slug(repo: SkillRepository, base_slug: str) -> str:
    root = get_skills_root_dir()
    if not await repo.exists_slug(base_slug) and not (root / base_slug).exists():
        return base_slug

    idx = 2
    while True:
        candidate = f"{base_slug}-v{idx}"
        if not await repo.exists_slug(candidate) and not (root / candidate).exists():
            return candidate
        idx += 1


def _resolve_skill_dir(item: Skill) -> Path:
    dir_path = Path(item.dir_path)
    if dir_path.is_absolute():
        return dir_path
    return (Path(sys_config.save_dir) / dir_path).resolve()


def _resolve_relative_path(skill_dir: Path, relative_path: str, *, allow_root: bool = False) -> tuple[Path, str]:
    rel = (relative_path or "").strip().replace("\\", "/")
    rel = rel.lstrip("/")
    if not rel and not allow_root:
        raise ValueError("path 不能为空")
    pure = PurePosixPath(rel) if rel else PurePosixPath(".")
    if ".." in pure.parts:
        raise ValueError("非法路径：不允许上级路径引用")

    target = (skill_dir / pure).resolve()
    try:
        target.relative_to(skill_dir)
    except ValueError:
        raise ValueError("非法路径：越界访问被拒绝") from None

    return target, rel


def _is_text_path(path: Path) -> bool:
    if path.name == "SKILL.md":
        return True
    suffix = path.suffix.lower()
    return suffix in TEXT_FILE_EXTENSIONS


def _build_tree(path: Path, base_dir: Path) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        rel = child.relative_to(base_dir).as_posix()
        if child.is_dir():
            children.append(
                {
                    "name": child.name,
                    "path": rel,
                    "is_dir": True,
                    "children": _build_tree(child, base_dir),
                }
            )
        else:
            children.append(
                {
                    "name": child.name,
                    "path": rel,
                    "is_dir": False,
                }
            )
    return children


async def import_skill_zip(
    db: AsyncSession,
    *,
    filename: str,
    file_bytes: bytes,
    created_by: str | None,
) -> Skill:
    if not filename.lower().endswith(".zip"):
        raise ValueError("仅支持上传 .zip 文件")

    repo = SkillRepository(db)
    skills_root = get_skills_root_dir()

    with tempfile.TemporaryDirectory(prefix=".skill-import-", dir=str(skills_root.parent)) as temp_root:
        temp_root_path = Path(temp_root)
        zip_path = temp_root_path / "upload.zip"
        extract_dir = temp_root_path / "extract"
        stage_dir = temp_root_path / "stage"
        extract_dir.mkdir(parents=True, exist_ok=True)

        zip_path.write_bytes(file_bytes)

        with zipfile.ZipFile(zip_path, "r") as zf:
            _validate_zip_paths(zf)
            zf.extractall(extract_dir)

        skill_md_files = list(extract_dir.rglob("SKILL.md"))
        if len(skill_md_files) != 1:
            raise ValueError("ZIP 必须且只能包含一个技能（检测到一个 SKILL.md）")

        skill_md_path = skill_md_files[0]
        source_skill_dir = skill_md_path.parent
        content = skill_md_path.read_text(encoding="utf-8")
        parsed_name, parsed_desc, _ = _parse_skill_markdown(content)

        final_slug = await _generate_available_slug(repo, parsed_name)
        final_name = parsed_name
        if final_slug != parsed_name:
            final_name = final_slug
            content = _rewrite_frontmatter_name(content, final_name)
            skill_md_path.write_text(content, encoding="utf-8")

        shutil.copytree(source_skill_dir, stage_dir)

        temp_target = skills_root / f".{final_slug}.tmp-{uuid.uuid4().hex[:8]}"
        if temp_target.exists():
            shutil.rmtree(temp_target)
        shutil.move(str(stage_dir), str(temp_target))

        final_dir = skills_root / final_slug
        if final_dir.exists():
            shutil.rmtree(temp_target, ignore_errors=True)
            raise ValueError(f"技能目录冲突，请重试: {final_slug}")
        temp_target.rename(final_dir)

        try:
            item = await repo.create(
                slug=final_slug,
                name=final_name,
                description=parsed_desc,
                dir_path=(Path("skills") / final_slug).as_posix(),
                created_by=created_by,
            )
        except Exception:
            shutil.rmtree(final_dir, ignore_errors=True)
            raise

    items = await repo.list_all()
    _set_skill_options_cache(items)
    return item


async def get_skill_or_raise(db: AsyncSession, slug: str) -> Skill:
    repo = SkillRepository(db)
    item = await repo.get_by_slug(slug)
    if not item:
        raise ValueError(f"技能 '{slug}' 不存在")
    return item


async def get_skill_tree(db: AsyncSession, slug: str) -> list[dict[str, Any]]:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError(f"技能目录不存在: {item.dir_path}")
    return _build_tree(skill_dir, skill_dir)


async def read_skill_file(db: AsyncSession, slug: str, relative_path: str) -> dict[str, Any]:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    target, rel = _resolve_relative_path(skill_dir, relative_path)
    if not target.exists() or not target.is_file():
        raise ValueError(f"文件不存在: {relative_path}")
    if not _is_text_path(target):
        raise ValueError("仅支持读取文本文件")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"文件编码不支持（仅支持 UTF-8）: {e}") from e

    return {"path": rel, "content": content}


async def create_skill_node(
    db: AsyncSession,
    *,
    slug: str,
    relative_path: str,
    is_dir: bool,
    content: str | None,
    updated_by: str | None,
) -> None:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    target, _ = _resolve_relative_path(skill_dir, relative_path)
    if target.exists():
        raise ValueError("目标已存在")

    if is_dir:
        target.mkdir(parents=True, exist_ok=False)
        return

    if not _is_text_path(target):
        raise ValueError("仅支持创建文本文件")

    parsed_name: str | None = None
    parsed_desc: str | None = None
    if target.name == "SKILL.md" and target.parent == skill_dir:
        parsed_name, parsed_desc, _ = _parse_skill_markdown(content or "")
        if parsed_name != item.slug:
            raise ValueError("SKILL.md frontmatter.name 必须与 skill slug 一致")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content or "", encoding="utf-8")

    if parsed_name is not None and parsed_desc is not None:
        repo = SkillRepository(db)
        await repo.update_metadata(item, name=parsed_name, description=parsed_desc, updated_by=updated_by)
        _set_skill_options_cache(await repo.list_all())


async def update_skill_file(
    db: AsyncSession,
    *,
    slug: str,
    relative_path: str,
    content: str,
    updated_by: str | None,
) -> None:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    target, _ = _resolve_relative_path(skill_dir, relative_path)
    if not target.exists() or not target.is_file():
        raise ValueError("文件不存在")
    if not _is_text_path(target):
        raise ValueError("仅支持编辑文本文件")

    parsed_name = None
    parsed_desc = None
    if target.name == "SKILL.md" and target.parent == skill_dir:
        parsed_name, parsed_desc, _ = _parse_skill_markdown(content)
        if parsed_name != item.slug:
            raise ValueError("SKILL.md frontmatter.name 必须与 skill slug 一致")

    target.write_text(content, encoding="utf-8")

    if parsed_name is not None and parsed_desc is not None:
        repo = SkillRepository(db)
        await repo.update_metadata(item, name=parsed_name, description=parsed_desc, updated_by=updated_by)
        _set_skill_options_cache(await repo.list_all())


async def delete_skill_node(db: AsyncSession, *, slug: str, relative_path: str) -> None:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    target, rel = _resolve_relative_path(skill_dir, relative_path, allow_root=False)
    if not target.exists():
        raise ValueError("目标不存在")

    if rel == "SKILL.md":
        raise ValueError("不允许删除根目录 SKILL.md")

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


async def export_skill_zip(db: AsyncSession, slug: str) -> tuple[str, str]:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError("技能目录不存在")

    fd, export_path = tempfile.mkstemp(prefix=f"skill-{slug}-", suffix=".zip")
    Path(export_path).unlink(missing_ok=True)
    export_file = Path(export_path)
    try:
        with zipfile.ZipFile(export_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in skill_dir.rglob("*"):
                arcname = Path(slug) / p.relative_to(skill_dir)
                zf.write(p, arcname.as_posix())
    except Exception:
        export_file.unlink(missing_ok=True)
        raise
    return export_path, f"{slug}.zip"


async def delete_skill(db: AsyncSession, *, slug: str) -> None:
    repo = SkillRepository(db)
    item = await repo.get_by_slug(slug)
    if not item:
        raise ValueError(f"技能 '{slug}' 不存在")

    skill_dir = _resolve_skill_dir(item)
    trash_dir: Path | None = None

    if skill_dir.exists():
        trash_dir = skill_dir.with_name(f".deleted-{slug}-{uuid.uuid4().hex[:8]}")
        skill_dir.rename(trash_dir)

    try:
        await repo.delete(item)
    except Exception:
        if trash_dir and trash_dir.exists():
            trash_dir.rename(skill_dir)
        raise

    if trash_dir and trash_dir.exists():
        shutil.rmtree(trash_dir, ignore_errors=True)

    _set_skill_options_cache(await repo.list_all())
