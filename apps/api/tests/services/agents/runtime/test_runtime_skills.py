# apps/api/tests/services/agents/runtime/test_runtime_skills.py

"""Tests for deferred runtime skill capabilities."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import Agent
from models.conversation import Conversation
from models.skills import Skill
from services.agent_runs import create_agent_run
from services.agent_runs.domain import RUN_STATUS_COMPLETED
from services.agents.runtime.events import EVENT_TOOL_CALL
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.load_context import load_agent_skills
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.skills import (
    READ_SKILL_DOCUMENT_TOOL_NAME,
    SKILL_DOCUMENTS_CAPABILITY_ID,
    build_skill_capabilities,
    skill_capability_id,
)
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_skill, build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class RuntimeSkillContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID
    skill_id: UUID


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def test_build_skill_capabilities_assembles_catalog_and_document_tool() -> None:
    user = build_user()
    workspace = build_workspace()
    plain_skill = build_skill(
        workspace=workspace,
        created_by=user,
        id=uuid4(),
        name="plain",
        human_name="Plain Skill",
        description="Plain guidance.",
        instructions="Use the plain workflow.",
    )
    documented_skill = build_skill(
        workspace=workspace,
        created_by=user,
        id=uuid4(),
        name="research",
        human_name="Research Skill",
        description="Research guidance.",
        instructions="Use the research workflow.",
        documentation_refs={
            "quick_start": _manifest_entry(
                markdown="workspaces/ws/skills/skill/docs/quick_start/converted.md",
                filename="Guide.md",
            ),
            "failed_doc": _manifest_entry(
                markdown=None,
                filename="Failed.pdf",
                status="failed",
            ),
        },
    )

    plain_capabilities = build_skill_capabilities([plain_skill])
    capabilities = build_skill_capabilities([plain_skill, documented_skill])

    assert [capability.id for capability in plain_capabilities] == [
        skill_capability_id(plain_skill)
    ]
    assert plain_capabilities[0].description == "Plain Skill: Plain guidance."
    assert plain_capabilities[0].defer_loading is True

    skill_capability_ids = [capability.id for capability in capabilities[:2]]
    assert skill_capability_ids == [
        skill_capability_id(plain_skill),
        skill_capability_id(documented_skill),
    ]
    assert capabilities[1].description == "Research Skill: Research guidance."
    loaded_instructions = "\n".join(capabilities[1].get_instructions())
    assert "## Skill documents" in loaded_instructions
    assert "quick_start: Guide.md" in loaded_instructions
    assert "failed_doc" not in loaded_instructions

    document_capability = capabilities[2]
    assert document_capability.id == SKILL_DOCUMENTS_CAPABILITY_ID
    assert document_capability.tools[0].name == READ_SKILL_DOCUMENT_TOOL_NAME


async def test_execute_run_records_skill_activation(
    db_session: AsyncSession,
) -> None:
    context = await _create_runtime_skill_context(db_session)
    skill = await db_session.get(Skill, context.skill_id)
    assert skill is not None
    capability_id = skill_capability_id(skill)
    sink = CollectingSink(
        run_id=context.run_id,
        conversation_id=context.conversation_id,
    )

    state = {"loaded": False}

    async def stream(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        if not state["loaded"]:
            state["loaded"] = True
            yield {
                0: DeltaToolCall(
                    name="load_capability",
                    json_args=json.dumps({"id": capability_id}),
                    tool_call_id="load-skill-call",
                )
            }
            return
        yield "done"

    result = await execute_run(
        db_session,
        conversation_id=context.conversation_id,
        run_id=context.run_id,
        user_prompt="Use the skill.",
        sink=sink,
        model=FunctionModel(
            stream_function=stream,
            model_name="skill-activation-model",
        ),
    )

    assert result.run.status == RUN_STATUS_COMPLETED
    assert result.output == "done"
    assert any(
        event.event == EVENT_TOOL_CALL and event.data["name"] == "load_capability"
        for event in sink.events
    )

    await db_session.refresh(skill)
    assert skill.last_used_at is not None


async def test_read_skill_document_requires_loaded_capability() -> None:
    skill = _documented_skill()
    tool = _read_skill_document_tool(skill)
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())

    with pytest.raises(ModelRetry, match="Call load_capability"):
        await tool.function(ctx, skill=skill.name, document="quick_start")


async def test_read_skill_document_returns_markdown_with_provenance(
    local_storage_settings: None,
) -> None:
    skill = _documented_skill()
    entry = skill.documentation_refs["quick_start"]
    assert isinstance(entry, dict)
    markdown_key = entry["markdown"]
    assert isinstance(markdown_key, str)

    provider = get_storage_provider()
    await provider.put_object(
        make_storage_object_ref(StorageBucket.PRIVATE, markdown_key),
        b"# Quick start\nFollow these steps.",
        content_type="text/markdown",
    )

    tool = _read_skill_document_tool(skill)
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())
    ctx.loaded_capability_ids.add(skill_capability_id(skill))

    content = await tool.function(ctx, skill=skill.name, document="quick_start")

    assert content.startswith("<skill-document skill='research' document='quick_start'>")
    assert "# Quick start\nFollow these steps." in content
    assert content.endswith("</skill-document>")


async def test_read_skill_document_accepts_original_filename(
    local_storage_settings: None,
) -> None:
    skill = _documented_skill()
    entry = skill.documentation_refs["quick_start"]
    assert isinstance(entry, dict)
    markdown_key = entry["markdown"]
    assert isinstance(markdown_key, str)

    provider = get_storage_provider()
    await provider.put_object(
        make_storage_object_ref(StorageBucket.PRIVATE, markdown_key),
        b"# Quick start\nFilename lookup works.",
        content_type="text/markdown",
    )

    tool = _read_skill_document_tool(skill)
    ctx = RunContext(deps=object(), model=TestModel(), usage=RunUsage())
    ctx.loaded_capability_ids.add(skill_capability_id(skill))

    content = await tool.function(ctx, skill=skill.name, document="Guide.md")

    assert content.startswith("<skill-document skill='research' document='quick_start'>")
    assert "# Quick start\nFilename lookup works." in content
    assert content.endswith("</skill-document>")


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


async def _create_runtime_skill_context(db: AsyncSession) -> RuntimeSkillContext:
    user = build_user(email=f"runtime-skill-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"runtime-skill-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()

    skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="research",
        human_name="Research Skill",
        description="Use for research workflows.",
        instructions="Follow the research workflow.",
    )
    db.add(skill)
    await db.flush()

    agent = Agent(
        name="Runtime Skill Agent",
        slug=f"runtime-skill-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
        skill_ids=[str(skill.id)],
    )
    db.add(agent)
    await db.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db.add(conversation)
    await db.flush()

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )

    return RuntimeSkillContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
        skill_id=skill.id,
    )


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
