# apps/api/tests/services/agents/runtime/test_runtime_skills.py

"""Tests for deferred runtime skill capabilities."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.skills import Skill
from services.agents.runtime.load_context import load_agent_skills
from services.agents.runtime.skills import (
    SKILL_DOCUMENTS_CAPABILITY_ID,
    build_skill_capabilities,
    record_skill_activation,
    skill_capability_id,
)
from tests.factories import (
    build_skill,
    build_user,
    build_workspace,
)
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


async def test_read_skill_document_requires_loaded_capability() -> None:
    skill = _documented_skill()
    tool = _read_skill_document_tool(skill)
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())

    with pytest.raises(ModelRetry, match="Call load_capability"):
        await tool.function(ctx, skill=skill.name, document="quick_start")


async def test_load_agent_skills_skips_malformed_and_unavailable_ids(
    db_session: AsyncSession,
) -> None:
    user = build_user(email=f"runtime-skills-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"runtime-skills-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    first_skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="first",
    )
    second_skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="second",
    )
    inactive_skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="inactive",
        is_active=False,
    )
    deleted_skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="deleted",
    )
    db_session.add_all([first_skill, second_skill, inactive_skill, deleted_skill])
    await db_session.flush()
    deleted_skill.soft_delete(deleted_by=user.id)

    agent = Agent(
        name="Skill Runtime Agent",
        slug=f"skill-runtime-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        skill_ids=[
            str(second_skill.id),
            str(inactive_skill.id),
            "not-a-uuid",
            str(deleted_skill.id),
            str(first_skill.id),
        ],
    )
    db_session.add(agent)
    await db_session.flush()

    skills = await load_agent_skills(db_session, agent)

    assert [skill.id for skill in skills] == [second_skill.id, first_skill.id]


async def test_platform_skill_activation_does_not_mutate_global_usage_state() -> None:
    user = build_user()
    workspace = build_workspace()
    platform_skill = build_skill(
        workspace=workspace,
        created_by=user,
        scope=ContentScope.PLATFORM,
        workspace_id=None,
    )
    run = AgentRun(id=uuid4(), agent_id=uuid4())
    part = SimpleNamespace(args={"id": skill_capability_id(platform_skill)})

    record_skill_activation([platform_skill], part, run=run)

    assert platform_skill.last_used_at is None


def _documented_skill() -> Skill:
    user = build_user()
    workspace = build_workspace()
    skill_id = uuid4()
    return build_skill(
        workspace=workspace,
        created_by=user,
        id=skill_id,
        name="research",
        human_name="Research Skill",
        description="Use for research workflows.",
        instructions="Follow the research workflow.",
        documentation_refs={
            "quick_start": _manifest_entry(
                markdown=(
                    f"workspaces/{workspace.id}/skills/{skill_id}/docs/"
                    "quick_start/uploads/test/converted.md"
                ),
                filename="Guide.md",
            )
        },
    )


def _read_skill_document_tool(skill: Skill):
    capabilities = build_skill_capabilities([skill])
    capability = next(
        capability for capability in capabilities if capability.id == SKILL_DOCUMENTS_CAPABILITY_ID
    )
    return capability.tools[0]


def _manifest_entry(
    *,
    markdown: str | None,
    filename: str,
    status: str = "ready",
) -> dict[str, Any]:
    return {
        "original": "workspaces/ws/skills/skill/docs/doc/uploads/test/original/guide.md",
        "markdown": markdown,
        "filename": filename,
        "content_type": "text/markdown",
        "size_bytes": 32,
        "markdown_size_bytes": 32 if markdown else None,
        "status": status,
        "error": None if status == "ready" else "Document could not be converted",
        "updated_at": datetime.now(UTC).isoformat(),
    }
