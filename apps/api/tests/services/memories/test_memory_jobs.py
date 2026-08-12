"""Memory embedding and expiry jobs."""

import importlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.audit_event import AuditEvent
from models.jobs import Job
from services.jobs.handlers.embed_memory import handle_embed_memory
from services.jobs.handlers.sweep_expired_memories import handle_sweep_expired_memories
from services.memories.ensure_sweep_job import ensure_memory_sweep_job
from tests.factories.jobs import build_job
from tests.factories.memories import build_memory
from tests.services.memories.conftest import MemoryContext
from tests.support.embeddings import FakeEmbeddingProvider


def _install_job_embeddings(monkeypatch) -> None:
    provider = FakeEmbeddingProvider()

    async def fake_embed_texts(_db, texts, *, workspace_id, **_attribution):
        del workspace_id
        return await provider.embed_texts(
            texts,
            model=settings.EMBEDDINGS_MODEL,
            dimensions=settings.EMBEDDINGS_DIMENSIONS,
        )

    embed_memory_module = importlib.import_module("services.memories.embed_memory")
    monkeypatch.setattr(embed_memory_module, "embed_texts", fake_embed_texts)


async def test_embed_job_stamps_metadata_and_is_idempotent(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    _install_job_embeddings(monkeypatch)
    memory = build_memory(
        workspace_id=memory_context.workspace.id,
        scope="agent",
        agent_id=memory_context.agent.id,
        created_by_user_id=memory_context.user.id,
    )
    job = build_job(
        kind="memory.embed",
        workspace_id=memory_context.workspace.id,
        subject_type="memory",
        subject_id=memory.id,
        payload={"memory_id": str(memory.id)},
    )
    db_session.add_all([memory, job])
    await db_session.flush()
    await handle_embed_memory(db_session, job)
    first_vector = list(memory.embedding)
    assert memory.embedding_provider == "fake"
    assert memory.embedding_model == settings.EMBEDDINGS_MODEL
    assert memory.embedding_dims == settings.EMBEDDINGS_DIMENSIONS
    await handle_embed_memory(db_session, job)
    assert list(memory.embedding) == first_vector


async def test_job_time_duplicate_keeps_both_active_and_audits_pair(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    _install_job_embeddings(monkeypatch)
    provider = FakeEmbeddingProvider()
    batch = await provider.embed_texts(
        ["Same title\n\nSame durable content."],
        model=settings.EMBEDDINGS_MODEL,
        dimensions=settings.EMBEDDINGS_DIMENSIONS,
    )
    existing = build_memory(
        workspace_id=memory_context.workspace.id,
        scope="agent",
        agent_id=memory_context.agent.id,
        title="Same title",
        content_md="Same durable content.",
        embedding=batch.vectors[0],
        embedding_provider=batch.provider,
        embedding_model=batch.model,
        embedding_dims=batch.dimensions,
    )
    pending = build_memory(
        workspace_id=memory_context.workspace.id,
        scope="agent",
        agent_id=memory_context.agent.id,
        title="Same title",
        content_md="Same durable content.",
        created_by_user_id=memory_context.user.id,
    )
    job = build_job(
        kind="memory.embed",
        workspace_id=memory_context.workspace.id,
        payload={"memory_id": str(pending.id)},
    )
    db_session.add_all([existing, pending, job])
    await db_session.flush()
    await handle_embed_memory(db_session, job)
    assert existing.status == pending.status == "active"
    assert existing.reinforcement_count == pending.reinforcement_count == 0
    event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == "memory",
            AuditEvent.resource_id == str(pending.id),
        )
    )
    assert event is not None
    assert event.details["existing_memory_id"] == str(existing.id)


async def test_sweep_archives_only_expired_and_reschedules(
    db_session: AsyncSession,
    memory_context: MemoryContext,
) -> None:
    now = datetime.now(UTC)
    expired = build_memory(
        workspace_id=memory_context.workspace.id,
        expires_at=now - timedelta(seconds=1),
    )
    future = build_memory(
        workspace_id=memory_context.workspace.id,
        expires_at=now + timedelta(days=1),
    )
    job = build_job(kind="memory.sweep_expired")
    db_session.add_all([expired, future, job])
    await db_session.flush()
    await handle_sweep_expired_memories(db_session, job)
    await db_session.refresh(expired)
    await db_session.refresh(future)
    assert expired.status == "archived"
    assert expired.archive_reason == "expired"
    assert future.status == "active"
    expiry_audit = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == "memory",
            AuditEvent.resource_id == str(expired.id),
        )
    )
    assert expiry_audit is not None
    assert expiry_audit.details == {
        "event": "archived",
        "reason": "expired",
    }
    scheduled = await db_session.scalar(
        select(Job).where(
            Job.kind == "memory.sweep_expired",
            Job.id != job.id,
        )
    )
    assert scheduled is not None
    assert scheduled.run_after > now


async def test_ensure_memory_sweep_is_idempotent(
    db_session: AsyncSession,
) -> None:
    first = await ensure_memory_sweep_job(db_session)
    second = await ensure_memory_sweep_job(db_session)
    assert first.id == second.id
