"""Write-time duplicate resolution and limits."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.memories.domain import MemoryProvenance
from services.memories.save_memory import save_memory
from tests.factories.users import build_user
from tests.factories.workspaces import build_workspace, build_workspace_membership
from tests.services.memories.conftest import (
    MemoryContext,
    install_fake_embeddings,
)


async def _save(
    db: AsyncSession,
    context: MemoryContext,
    *,
    title: str = "Client preference",
    content: str = "The client prefers concise weekly reports.",
    scope: str = "agent",
    kind: str = "note",
    **kwargs,
):
    return await save_memory(
        db,
        workspace=context.workspace,
        agent=context.agent,
        user=context.user,
        scope=scope,
        kind=kind,
        memory_type="preference",
        title=title,
        content_md=content,
        provenance=context.provenance,
        **kwargs,
    )


async def test_near_duplicate_requires_explicit_resolution(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    created = await _save(db_session, memory_context)
    duplicate = await _save(db_session, memory_context)
    assert created.status == "created"
    assert duplicate.status == "near_duplicate"
    assert duplicate.existing_memory.id == created.memory.id
    assert (
        await db_session.scalar(
            select(func.count(AgentMemory.id)).where(
                AgentMemory.workspace_id == memory_context.workspace.id
            )
        )
        == 1
    )


async def test_duplicate_of_reinforces_current_neighbour(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    created = await _save(db_session, memory_context)
    reinforced = await _save(
        db_session,
        memory_context,
        duplicate_of=created.memory.id,
    )
    assert reinforced.status == "reinforced"
    assert reinforced.memory.id == created.memory.id
    assert reinforced.memory.reinforcement_count == 1
    assert reinforced.memory.confidence == 0.9


async def test_duplicate_reinforcement_caps_confidence_at_one(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    created = await _save(db_session, memory_context)
    created.memory.confidence = 0.95
    await db_session.flush()

    reinforced = await _save(
        db_session,
        memory_context,
        duplicate_of=created.memory.id,
    )

    assert reinforced.memory.confidence == 1.0


async def test_below_threshold_content_inserts_without_override(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    first = await _save(db_session, memory_context)
    second = await _save(
        db_session,
        memory_context,
        title="Billing date",
        content="Invoices are paid on the fifteenth day of each month.",
    )

    assert first.status == second.status == "created"
    assert (
        await db_session.scalar(
            select(func.count(AgentMemory.id)).where(
                AgentMemory.workspace_id == memory_context.workspace.id
            )
        )
        == 2
    )


async def test_save_as_new_keeps_a_distinct_active_row(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    first = await _save(db_session, memory_context)
    second = await _save(db_session, memory_context, save_as_new=True)
    assert second.status == "created"
    assert second.memory.id != first.memory.id
    assert (
        await db_session.scalar(
            select(func.count(AgentMemory.id)).where(
                AgentMemory.workspace_id == memory_context.workspace.id
            )
        )
        == 2
    )


async def test_same_content_in_another_scope_does_not_deduplicate(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    agent_memory = await _save(db_session, memory_context, scope="agent")
    user_memory = await _save(db_session, memory_context, scope="user")
    assert agent_memory.status == user_memory.status == "created"
    assert agent_memory.memory.id != user_memory.memory.id


async def test_embedding_failure_queues_a_pending_row(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch, fail=True)
    created = await _save(db_session, memory_context)
    assert created.memory.embedding is None
    job = await db_session.scalar(
        select(Job).where(
            Job.kind == "memory.embed",
            Job.subject_id == created.memory.id,
        )
    )
    assert job is not None
    assert job.payload == {"memory_id": str(created.memory.id)}


async def test_core_cap_rejects_with_actionable_message(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    monkeypatch.setattr(settings, "MEMORY_CORE_MAX_PER_SCOPE", 1)
    await _save(db_session, memory_context, kind="core")
    try:
        await _save(
            db_session,
            memory_context,
            kind="core",
            title="Another identity fact",
            content="A completely unrelated preference about billing.",
        )
    except AppValidationError as exc:
        assert "update or forget" in exc.message
    else:
        raise AssertionError("Expected the core-memory cap to reject the write")


async def test_expired_rows_do_not_affect_deduplication_or_the_core_cap(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    expired_note = await _save(db_session, memory_context)
    expired_note.memory.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired_core = await _save(
        db_session,
        memory_context,
        kind="core",
        title="Expired identity",
        content="An identity fact that has expired.",
    )
    expired_core.memory.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    monkeypatch.setattr(settings, "MEMORY_CORE_MAX_PER_SCOPE", 1)

    replacement_note = await _save(db_session, memory_context)
    replacement_core = await _save(
        db_session,
        memory_context,
        kind="core",
        title="Current identity",
        content="A distinct and current identity fact.",
    )

    assert replacement_note.status == "created"
    assert replacement_core.status == "created"


async def test_concurrent_duplicate_writes_are_serialized(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    suffix = uuid4().hex
    user = build_user(email=f"memory-concurrent-{suffix}@example.com")
    workspace = build_workspace(slug=f"memory-concurrent-{suffix[:10]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
    )
    async with committed_db_session_factory() as db:
        db.add_all([user, workspace, membership])
        await db.flush()
        agent = Agent(
            name="Concurrent Memory Agent",
            slug=f"memory-concurrent-{suffix[:8]}",
            instructions="Remember carefully.",
            workspace_id=workspace.id,
            created_by=user.id,
            tool_names=[],
        )
        db.add(agent)
        await db.commit()

    context = MemoryContext(
        user=user,
        workspace=workspace,
        membership=membership,
        agent=agent,
        provenance=MemoryProvenance(
            source="interactive",
            source_conversation_id=None,
            source_run_id=None,
            created_by="agent",
            created_by_user_id=user.id,
        ),
    )

    async def concurrent_save():
        async with committed_db_session_factory() as db:
            result = await _save(db, context)
            await db.commit()
            return result.status

    try:
        statuses = await asyncio.gather(concurrent_save(), concurrent_save())
        assert sorted(statuses) == ["created", "near_duplicate"]
        async with committed_db_session_factory() as db:
            assert (
                await db.scalar(
                    select(func.count(AgentMemory.id)).where(
                        AgentMemory.workspace_id == workspace.id
                    )
                )
                == 1
            )
    finally:
        async with committed_db_session_factory() as db:
            await db.execute(delete(AgentMemory).where(AgentMemory.workspace_id == workspace.id))
            await db.execute(delete(Agent).where(Agent.workspace_id == workspace.id))
            await db.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
            )
            await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await db.execute(delete(User).where(User.id == user.id))
            await db.commit()
