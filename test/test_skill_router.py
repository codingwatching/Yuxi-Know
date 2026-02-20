from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from server.routers.skill_router import skills
from server.utils.auth_middleware import get_admin_user, get_db, get_superadmin_user
from src.storage.postgres.models_business import Skill, User


def _build_app(*, allow_superadmin: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(skills, prefix="/api")

    async def fake_db():
        return None

    async def fake_admin_user():
        return User(
            username="admin",
            user_id="admin",
            password_hash="x",
            role="admin",
        )

    async def fake_superadmin_user():
        if not allow_superadmin:
            raise HTTPException(status_code=403, detail="需要超级管理员权限")
        return User(
            username="root",
            user_id="root",
            password_hash="x",
            role="superadmin",
        )

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_admin_user] = fake_admin_user
    app.dependency_overrides[get_superadmin_user] = fake_superadmin_user
    return app


def test_list_skills_route_returns_data(monkeypatch):
    async def fake_list_skills(_db):
        return [
            Skill(
                slug="demo",
                name="demo",
                description="demo skill",
                dir_path="skills/demo",
            )
        ]

    monkeypatch.setattr("server.routers.skill_router.list_skills", fake_list_skills)

    app = _build_app(allow_superadmin=True)
    client = TestClient(app)
    resp = client.get("/api/system/skills")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["success"] is True
    assert payload["data"][0]["slug"] == "demo"


def test_import_skill_requires_superadmin():
    app = _build_app(allow_superadmin=False)
    client = TestClient(app)

    resp = client.post(
        "/api/system/skills/import",
        files={"file": ("demo.zip", b"not zip", "application/zip")},
    )
    assert resp.status_code == 403


def test_update_skill_file_passes_operator(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_update_skill_file(_db, *, slug, relative_path, content, updated_by):
        captured["slug"] = slug
        captured["relative_path"] = relative_path
        captured["content"] = content
        captured["updated_by"] = updated_by

    monkeypatch.setattr("server.routers.skill_router.update_skill_file", fake_update_skill_file)

    app = _build_app(allow_superadmin=True)
    client = TestClient(app)

    resp = client.put(
        "/api/system/skills/demo/file",
        json={
            "path": "SKILL.md",
            "content": "---\nname: demo\ndescription: demo\n---\n# Demo\n",
        },
    )
    assert resp.status_code == 200, resp.text
    assert captured["slug"] == "demo"
    assert captured["relative_path"] == "SKILL.md"
    assert captured["updated_by"] == "root"
