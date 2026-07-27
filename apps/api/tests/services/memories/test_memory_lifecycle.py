"""Memory updates and archival preserve lifecycle invariants."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent_memories import AgentMemory
from models.audit_event import AuditEvent
from models.jobs import Job
from services.memories import forget_memory, save_memory, update_memory
from tests.services.memories.conftest import MemoryContext, install_fake_embeddings


async def test_content_update_supersedes_and_forget_archives(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    created = await save_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        scope="agent",
        kind="note",
        memory_type="fact",
        title="Account owner",
        content_md="Alex owns the account.",
        provenance=memory_context.provenance,
    )
    updated = await update_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        memory_id=created.memory.id,
        content_md="Morgan owns the account.",
        provenance=memory_context.provenance,
    )
    predecessor = await db_session.get(AgentMemory, created.memory.id)
    assert predecessor.status == "superseded"
    assert predecessor.superseded_by_id == updated.memory.id
    assert updated.memory.status == "active"
    assert updated.superseded_memory_id == predecessor.id

    forgotten = await forget_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        memory_id=updated.memory.id,
        reason="No longer relevant",
    )
    assert forgotten.memory.status == "archived"
    assert forgotten.memory.archive_reason == "forgotten"
    assert await db_session.scalar(select(AgentMemory).where(AgentMemory.id == forgotten.memory.id))
    events = list(
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_type == "memory",
                AuditEvent.resource_id.in_([str(predecessor.id), str(forgotten.memory.id)]),
            )
        )
    )
    assert {event.details["event"] for event in events} == {
        "superseded",
        "archived",
    }


async def test_forget_rejects_a_superseded_predecessor(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    created = await save_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        scope="agent",
        kind="note",
        memory_type="fact",
        title="Account owner",
        content_md="Alex owns the account.",
        provenance=memory_context.provenance,
    )
    updated = await update_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        memory_id=created.memory.id,
        content_md="Morgan owns the account.",
        provenance=memory_context.provenance,
    )

    with pytest.raises(ConflictError, match="successor link"):
        await forget_memory(
            db_session,
            workspace=memory_context.workspace,
            agent=memory_context.agent,
            user=memory_context.user,
            memory_id=created.memory.id,
        )

    predecessor = await db_session.get(AgentMemory, created.memory.id)
    assert predecessor.status == "superseded"
    assert predecessor.superseded_by_id == updated.memory.id


async def test_content_supersession_preserves_existing_expiry_by_default(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    expires_at = datetime.now(UTC) + timedelta(days=12)
    created = await save_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        scope="agent",
        kind="note",
        memory_type="fact",
        title="Renewal date",
        content_md="The renewal is in June.",
        expires_in_days=12,
        provenance=memory_context.provenance,
    )
    created.memory.expires_at = expires_at
    await db_session.flush()

    updated = await update_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        memory_id=created.memory.id,
        content_md="The renewal is in July.",
        provenance=memory_context.provenance,
    )

    assert updated.memory.expires_at == expires_at


async def test_title_update_refreshes_embedding(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    created = await save_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        scope="agent",
        kind="note",
        memory_type="fact",
        title="Old title",
        content_md="A durable account fact.",
        provenance=memory_context.provenance,
    )
    original_vector = list(created.memory.embedding)

    updated = await update_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        memory_id=created.memory.id,
        title="New title",
        provenance=memory_context.provenance,
    )

    assert list(updated.memory.embedding) != original_vector
    assert updated.memory.embedding_provider == "fake"


async def test_title_update_queues_reembedding_when_provider_is_unavailable(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    created = await save_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        scope="agent",
        kind="note",
        memory_type="fact",
        title="Old title",
        content_md="A durable account fact.",
        provenance=memory_context.provenance,
    )
    install_fake_embeddings(monkeypatch, fail=True)

    updated = await update_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        memory_id=created.memory.id,
        title="New title",
        provenance=memory_context.provenance,
    )

    assert updated.memory.embedding is None
    assert await db_session.scalar(
        select(Job).where(
            Job.kind == "memory.embed",
            Job.subject_id == updated.memory.id,
        )
    )
