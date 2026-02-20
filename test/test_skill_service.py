from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from src.services import skill_service as svc
from src.storage.postgres.models_business import Skill


def _build_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def test_parse_skill_markdown_ok():
    content = (
        "---\n"
        "name: demo-skill\n"
        "description: demo description\n"
        "---\n"
        "# Demo\n"
    )
    name, desc, meta = svc._parse_skill_markdown(content)
    assert name == "demo-skill"
    assert desc == "demo description"
    assert meta["name"] == "demo-skill"


def test_parse_skill_markdown_requires_frontmatter():
    with pytest.raises(ValueError, match="frontmatter"):
        svc._parse_skill_markdown("# missing")


def test_get_skill_prompt_metadata_by_slugs_dedup_and_skip_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        svc,
        "_skill_prompt_metadata_cache",
        {
            "alpha": {"name": "alpha", "description": "a", "path": "/skills/alpha/SKILL.md"},
            "beta": {"name": "beta", "description": "b", "path": "/skills/beta/SKILL.md"},
        },
    )

    result = svc.get_skill_prompt_metadata_by_slugs(["beta", "missing", "alpha", "beta"])
    assert [item["name"] for item in result] == ["beta", "alpha"]
    assert [item["path"] for item in result] == ["/skills/beta/SKILL.md", "/skills/alpha/SKILL.md"]


def test_resolve_relative_path_blocks_traversal(tmp_path: Path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="上级路径"):
        svc._resolve_relative_path(skill_dir, "../outside.txt")


@pytest.mark.asyncio
async def test_import_skill_zip_conflict_rewrite_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(svc.sys_config, "save_dir", str(tmp_path))

    class FakeRepo:
        existing_slugs = {"demo"}
        created_item: Skill | None = None

        def __init__(self, _db):
            pass

        async def exists_slug(self, slug: str) -> bool:
            return slug in self.__class__.existing_slugs

        async def create(
            self,
            *,
            slug: str,
            name: str,
            description: str,
            dir_path: str,
            created_by: str | None,
        ) -> Skill:
            item = Skill(
                slug=slug,
                name=name,
                description=description,
                dir_path=dir_path,
                created_by=created_by,
                updated_by=created_by,
            )
            self.__class__.existing_slugs.add(slug)
            self.__class__.created_item = item
            return item

        async def list_all(self) -> list[Skill]:
            return [self.__class__.created_item] if self.__class__.created_item else []

    monkeypatch.setattr(svc, "SkillRepository", FakeRepo)

    zip_bytes = _build_zip(
        {
            "demo/SKILL.md": (
                "---\n"
                "name: demo\n"
                "description: this is demo\n"
                "---\n"
                "# Demo\n"
            ),
            "demo/prompts/system.md": "You are demo skill",
        }
    )

    item = await svc.import_skill_zip(
        None,
        filename="demo.zip",
        file_bytes=zip_bytes,
        created_by="root",
    )

    assert item.slug == "demo-v2"
    assert item.name == "demo-v2"
    skill_md = (tmp_path / "skills" / "demo-v2" / "SKILL.md").read_text(encoding="utf-8")
    assert "name: demo-v2" in skill_md


@pytest.mark.asyncio
async def test_update_skill_md_syncs_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(svc.sys_config, "save_dir", str(tmp_path))
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: old\n---\n# old\n",
        encoding="utf-8",
    )

    item = Skill(
        slug="demo",
        name="demo",
        description="old",
        dir_path="skills/demo",
        created_by="root",
        updated_by="root",
    )

    async def fake_get_skill_or_raise(_db, _slug: str):
        return item

    updates: dict[str, str | None] = {}

    class FakeRepo:
        def __init__(self, _db):
            pass

        async def update_metadata(
            self,
            _item: Skill,
            *,
            name: str,
            description: str,
            updated_by: str | None,
        ) -> Skill:
            updates["name"] = name
            updates["description"] = description
            updates["updated_by"] = updated_by
            return item

        async def list_all(self) -> list[Skill]:
            return [item]

    monkeypatch.setattr(svc, "get_skill_or_raise", fake_get_skill_or_raise)
    monkeypatch.setattr(svc, "SkillRepository", FakeRepo)

    new_content = (
        "---\n"
        "name: demo\n"
        "description: updated desc\n"
        "---\n"
        "# updated\n"
    )
    await svc.update_skill_file(
        None,
        slug="demo",
        relative_path="SKILL.md",
        content=new_content,
        updated_by="admin",
    )

    assert updates["name"] == "demo"
    assert updates["description"] == "updated desc"
    assert updates["updated_by"] == "admin"
    saved_content = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "description: updated desc" in saved_content
