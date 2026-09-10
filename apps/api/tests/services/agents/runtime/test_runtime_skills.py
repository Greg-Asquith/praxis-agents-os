# apps/api/tests/services/agents/runtime/test_runtime_skills.py

"""Tests for deferred runtime skill capabilities."""

import json
import runpy
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ModelMessage,
    RetryPromptPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_maintenance_async_db_session_factory
from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
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
    record_skill_activation,
    skill_capability_id,
)
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import (
    build_skill,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.storage import reset_storage_provider_cache
from utils.content import ContentScope

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


@pytest.mark.parametrize("legacy_history", [False, True])
async def test_execute_run_records_skill_activation(
    db_session: AsyncSession,
    local_storage_settings: None,
    legacy_history: bool,
) -> None:
    context = await _create_runtime_skill_context(db_session)
    skill = await db_session.get(Skill, context.skill_id)
    assert skill is not None
    capability_id = skill_capability_id(skill)
    markdown_key = (
        f"workspaces/{context.workspace_id}/skills/{skill.id}/docs/quick_start/converted.md"
    )
    skill.documentation_refs = {
        "quick_start": _manifest_entry(markdown=markdown_key, filename="Guide.md")
    }
    await db_session.flush()
    await get_storage_provider().put_object(
        make_storage_object_ref(StorageBucket.PRIVATE, markdown_key),
        b"# Guide\nUse the approved workflow.",
        content_type="text/markdown",
    )
    sink = CollectingSink(
        run_id=context.run_id,
        conversation_id=context.conversation_id,
    )

    requests = []
    call_number = 0
    document_args = {"skill": skill.name, "document": "quick_start"}
    turns = [
        (READ_SKILL_DOCUMENT_TOOL_NAME, document_args),
        ("load_capability", {"id": capability_id}),
        (READ_SKILL_DOCUMENT_TOOL_NAME, document_args),
    ]

    async def stream(
        _messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal call_number
        requests.append((list(_messages), _info))
        if len(requests) <= len(turns):
            name, args = turns[len(requests) - 1]
            call_number += 1
            yield {
                0: DeltaToolCall(
                    name=name,
                    json_args=json.dumps(args),
                    tool_call_id=f"skill-{call_number}",
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
    assert len(requests) == 4
    assert skill.instructions not in (requests[0][1].instructions or "")
    [loaded] = [
        part
        for message in requests[2][0]
        for part in message.parts
        if isinstance(part, LoadCapabilityReturnPart)
    ]
    assert skill.instructions in loaded.instructions
    retries = [
        part
        for message in requests[1][0]
        for part in message.parts
        if isinstance(part, RetryPromptPart)
    ]
    assert any("Call load_capability" in str(part.content) for part in retries)
    returns = [
        part
        for message in requests[3][0]
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == READ_SKILL_DOCUMENT_TOOL_NAME
    ]
    assert len(returns) == 1
    assert "Use the approved workflow." in str(returns[0].content)

    if legacy_history:
        rows = (
            await db_session.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == context.conversation_id
                )
            )
        ).all()
        for row in rows:
            parts = json.loads(json.dumps(row.parts))
            for part in parts.get("parts", []):
                if (
                    part.get("tool_kind") == "capability-load"
                    and part.get("part_kind") == "tool-call"
                ):
                    part["args"] = {"id": f"skill:{skill.id}"}
                    row.parts = parts
        await db_session.commit()
        await _migrate_skill_ids(db_session, "upgrade")
        await db_session.commit()
        for row in rows:
            await db_session.refresh(row)

    next_run = await create_agent_run(
        db_session,
        conversation_id=context.conversation_id,
        agent_id=context.agent_id,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        trigger="interactive",
    )
    requests.clear()
    turns[:] = [(READ_SKILL_DOCUMENT_TOOL_NAME, document_args)]
    continued = await execute_run(
        db_session,
        conversation_id=context.conversation_id,
        run_id=next_run.id,
        user_prompt="Use the skill again.",
        model=FunctionModel(stream_function=stream, model_name="skill-reload-model"),
    )
    assert continued.run.status == RUN_STATUS_COMPLETED
    assert len(requests) == 2
    [restored] = [
        part
        for message in requests[0][0]
        for part in message.parts
        if isinstance(part, LoadCapabilityReturnPart)
    ]
    assert restored.instructions == loaded.instructions
    returns = [part for part in requests[1][0][-1].parts if isinstance(part, ToolReturnPart)]
    assert any("Use the approved workflow." in str(part.content) for part in returns)


async def test_skill_id_migration_preserves_other_history_and_approval_state(
    db_session: AsyncSession,
) -> None:
    context = await _create_runtime_skill_context(db_session)
    legacy_id = f"skill:{context.skill_id}"
    other_id = f"skill:{uuid4()}"
    calls = [
        LoadCapabilityCallPart(args=args, tool_call_id=f"load-{index}")
        for index, args in enumerate([{"id": legacy_id}, json.dumps({"id": other_id})])
    ]
    response = {
        "kind": "response",
        "metadata": {"id": legacy_id},
        "parts": [
            {
                "part_kind": call.part_kind,
                "tool_kind": call.tool_kind,
                "tool_name": call.tool_name,
                "tool_call_id": call.tool_call_id,
                "args": call.args,
            }
            for call in calls
        ],
    }
    response["parts"].extend(
        [
            {"part_kind": "text", "content": legacy_id},
            {"part_kind": "tool-call", "tool_name": "ordinary", "args": {"id": legacy_id}},
            {
                "part_kind": "tool-return",
                "tool_kind": "capability-load",
                "content": {"id": legacy_id},
            },
        ]
        + [
            {"part_kind": "tool-call", "tool_kind": "capability-load", "args": args}
            for args in ["not-json", "[]", {"id": "skill:not-a-uuid"}, {"id": None}]
        ]
    )
    request = {"kind": "request", "parts": [{"part_kind": "user-prompt", "content": legacy_id}]}
    history = [response, request]
    metadata = {
        "approval_state": {
            "message_history": history,
        },
        "approval_continuation": {
            "deferred_tool_results": {
                "approvals": {"write": True},
                "metadata": {"write": {"id": legacy_id}},
            },
        },
        "code_mode_state": {"snapshot_b64": "c25hcHNob3Q=", "code": f"print({legacy_id!r})"},
        "id": legacy_id,
    }
    message = ConversationMessage(
        conversation_id=context.conversation_id,
        workspace_id=context.workspace_id,
        role="assistant",
        parts=response,
        metadata_json={"id": legacy_id},
        sequence=1,
    )
    run = await db_session.get(AgentRun, context.run_id)
    assert run is not None
    run.status = "completed"
    run.metadata_json = metadata
    await db_session.flush()
    delegated_run = AgentRun(
        conversation_id=context.conversation_id,
        agent_id=context.agent_id,
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        parent_run_id=run.id,
        delegation_depth=1,
        trigger="delegated",
        status="awaiting_approval",
        metadata_json=metadata,
    )
    db_session.add_all([message, delegated_run])
    await db_session.flush()

    await _migrate_skill_ids(db_session, "upgrade")
    await db_session.refresh(message)
    await db_session.refresh(run)
    await db_session.refresh(delegated_run)

    migrated = message.parts
    assert migrated["parts"][0]["args"] == {"id": f"skill-{context.skill_id}"}
    assert json.loads(migrated["parts"][1]["args"]) == {"id": other_id.replace(":", "-")}
    assert migrated["parts"][0]["tool_call_id"] == "load-0"
    assert migrated["parts"][2:] == response["parts"][2:]
    assert migrated["metadata"] == response["metadata"]
    assert message.metadata_json == {"id": legacy_id}
    expected_metadata = {
        **metadata,
        "approval_state": {**metadata["approval_state"], "message_history": [migrated, request]},
    }
    assert run.metadata_json == delegated_run.metadata_json == expected_metadata

    await _migrate_skill_ids(db_session, "upgrade")
    await db_session.refresh(message)
    await db_session.refresh(run)
    assert message.parts == migrated
    assert run.metadata_json == expected_metadata

    await _migrate_skill_ids(db_session, "downgrade")
    await db_session.refresh(message)
    await db_session.refresh(run)
    await db_session.refresh(delegated_run)
    assert message.parts == response
    assert run.metadata_json == delegated_run.metadata_json == metadata


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


async def test_load_agent_skills_includes_platform_skills_in_configured_order(
    db_session: AsyncSession,
) -> None:
    user = build_user(email=f"runtime-platform-skills-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"runtime-platform-skills-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    workspace_skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="workspace-guidance",
    )
    db_session.add(workspace_skill)
    await db_session.flush()

    platform_skill = build_skill(
        workspace=workspace,
        created_by=user,
        name="platform-guidance",
        scope=ContentScope.PLATFORM,
        workspace_id=None,
    )
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        maintenance_db.add(platform_skill)
        await maintenance_db.commit()

    agent = Agent(
        name="Platform Skill Runtime Agent",
        slug=f"platform-skill-runtime-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        skill_ids=[str(platform_skill.id), str(workspace_skill.id)],
    )
    db_session.add(agent)
    await db_session.flush()

    skills = await load_agent_skills(db_session, agent)

    assert [skill.id for skill in skills] == [platform_skill.id, workspace_skill.id]
    capabilities = build_skill_capabilities(skills)
    assert [capability.id for capability in capabilities] == [
        skill_capability_id(platform_skill),
        skill_capability_id(workspace_skill),
    ]


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


async def _create_runtime_skill_context(db: AsyncSession) -> RuntimeSkillContext:
    user = build_user(email=f"runtime-skill-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"runtime-skill-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
    )
    db.add_all([user, workspace, membership])
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


async def _migrate_skill_ids(db: AsyncSession, direction: str) -> None:
    migration = runpy.run_path(
        str(
            Path(__file__).parents[4] / "alembic/versions/core/0052_migrate_skill_capability_ids.py"
        )
    )

    def migrate(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migration[direction]()

    connection = await db.connection()
    await connection.run_sync(migrate)
