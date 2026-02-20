from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import SystemMessage

import src.agents.common.middlewares.runtime_config_middleware as runtime_middleware
from src.agents.common.middlewares.runtime_config_middleware import RuntimeConfigMiddleware
from src.services import skill_service


@dataclass
class _FakeTool:
    name: str


@dataclass
class _FakeRequest:
    runtime: Any
    tools: list[Any]
    system_message: SystemMessage

    def override(self, **kwargs):
        return _FakeRequest(
            runtime=kwargs.get("runtime", self.runtime),
            tools=kwargs.get("tools", self.tools),
            system_message=kwargs.get("system_message", self.system_message),
        )


async def _echo_handler(request):
    return request


def _build_request(*, skills: list[str], tools: list[str], system_prompt: str = "你是助手") -> _FakeRequest:
    context = SimpleNamespace(system_prompt=system_prompt, skills=skills)
    runtime = SimpleNamespace(context=context)
    return _FakeRequest(
        runtime=runtime,
        tools=[_FakeTool(name=name) for name in tools],
        system_message=SystemMessage(content=[{"type": "text", "text": "base"}]),
    )


def _extract_appended_prompt(request: _FakeRequest) -> str:
    return request.system_message.content_blocks[-1]["text"]


def _build_middleware() -> RuntimeConfigMiddleware:
    return RuntimeConfigMiddleware(
        enable_model_override=False,
        enable_tools_override=False,
        enable_system_prompt_override=True,
        enable_skills_prompt_override=True,
    )


@pytest.mark.asyncio
async def test_injects_skills_section_when_skills_configured_and_read_file_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        runtime_middleware,
        "get_skill_prompt_metadata_by_slugs",
        lambda _slugs: [
            {
                "name": "research-report",
                "description": "Write structured research reports",
                "path": "/skills/research-report/SKILL.md",
            }
        ],
    )
    middleware = _build_middleware()
    request = _build_request(skills=["research-report"], tools=["read_file"])

    result = await middleware.awrap_model_call(request, _echo_handler)
    prompt = _extract_appended_prompt(result)

    assert "## Skills System" in prompt
    assert "**Skills Skills**: `/skills/` (higher priority)" in prompt
    assert "- **research-report**: Write structured research reports" in prompt
    assert "Read `/skills/research-report/SKILL.md` for full instructions" in prompt
    assert "Recognize when a skill applies" in prompt
    assert "当前时间：" in prompt


@pytest.mark.asyncio
async def test_skips_skills_section_when_context_skills_empty(monkeypatch: pytest.MonkeyPatch):
    def _should_not_call(_slugs: list[str]):
        raise AssertionError("should not query skills metadata when context.skills is empty")

    monkeypatch.setattr(runtime_middleware, "get_skill_prompt_metadata_by_slugs", _should_not_call)
    middleware = _build_middleware()
    request = _build_request(skills=[], tools=["read_file"])

    result = await middleware.awrap_model_call(request, _echo_handler)
    prompt = _extract_appended_prompt(result)

    assert "## Skills System" not in prompt


@pytest.mark.asyncio
async def test_skips_skills_section_without_read_file_and_logs_warning(monkeypatch: pytest.MonkeyPatch):
    warnings: list[str] = []
    fake_logger = SimpleNamespace(
        debug=lambda *_args, **_kwargs: None,
        warning=lambda message: warnings.append(message),
    )
    monkeypatch.setattr(runtime_middleware, "logger", fake_logger)
    monkeypatch.setattr(
        runtime_middleware,
        "get_skill_prompt_metadata_by_slugs",
        lambda _slugs: (_ for _ in ()).throw(AssertionError("should not query metadata without read_file")),
    )
    middleware = _build_middleware()
    request = _build_request(skills=["research-report"], tools=["write_file"])

    result = await middleware.awrap_model_call(request, _echo_handler)
    prompt = _extract_appended_prompt(result)

    assert "## Skills System" not in prompt
    assert any("read_file unavailable" in msg for msg in warnings)


@pytest.mark.asyncio
async def test_injects_skills_in_input_order_with_dedup_and_invalid_slug_skipped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        skill_service,
        "_skill_prompt_metadata_cache",
        {
            "beta": {
                "name": "beta",
                "description": "beta skill",
                "path": "/skills/beta/SKILL.md",
            },
            "alpha": {
                "name": "alpha",
                "description": "alpha skill",
                "path": "/skills/alpha/SKILL.md",
            },
        },
    )
    middleware = _build_middleware()
    request = _build_request(skills=["beta", "missing", "alpha", "beta"], tools=["read_file"])

    result = await middleware.awrap_model_call(request, _echo_handler)
    prompt = _extract_appended_prompt(result)

    beta_line = "- **beta**: beta skill"
    alpha_line = "- **alpha**: alpha skill"
    assert beta_line in prompt
    assert alpha_line in prompt
    assert prompt.find(beta_line) < prompt.find(alpha_line)
    assert prompt.count(beta_line) == 1
    assert "missing" not in prompt
