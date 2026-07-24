# apps/api/tests/services/kb/test_sweep_deleted.py

"""Knowledge-base retention sweep tests."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from models.kb import KBChunk, KBDocument
from services.jobs.handlers.sweep_deleted_kb_documents import (
    handle_sweep_deleted_kb_documents,
)
from services.kb.ensure_sweep_job import ensure_kb_sweep_job
from services.kb.sweep_deleted_documents import sweep_deleted_kb_documents
from tests.factories import build_job, build_kb_chunk, build_kb_document
from tests.services.kb.conftest import KBActors

pytestmark = pytest.mark.asyncio


async def test_sweep_deletes_only_expired_tombstones_and_cascades_chunks(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    now = datetime.now(UTC)
    expired = build_kb_document(
        workspace=kb_actors.workspace,
        deleted=True,
        deleted_at=now - timedelta(days=31),
        chunk_count=1,
    )
    fresh = build_kb_document(
        workspace=kb_actors.workspace,
        deleted=True,
        deleted_at=now - timedelta(days=1),
    )
    live = build_kb_document(workspace=kb_actors.workspace)
    chunk = build_kb_chunk(document=expired)
    db_session.add_all([expired, fresh, live])
    await db_session.flush()
    db_session.add(chunk)
    await db_session.flush()

    assert await sweep_deleted_kb_documents(db_session, now=now) == 1
    await db_session.flush()

    assert await db_session.get(KBDocument, expired.id) is None
    assert (
        await db_session.scalar(
            select(func.count(KBChunk.id)).where(KBChunk.document_id == expired.id)
        )
        == 0
    )
    assert await db_session.get(KBDocument, fresh.id) is not None
    assert await db_session.get(KBDocument, live.id) is not None


async def test_ensure_sweep_is_idempotent_and_handler_reschedules(
    db_session: AsyncSession,
) -> None:
    first = await ensure_kb_sweep_job(db_session)
    second = await ensure_kb_sweep_job(db_session)
    assert first.id == second.id

    running_job = build_job(kind="kb.sweep_deleted", status="running")
    db_session.add(running_job)
    await db_session.flush()
    await handle_sweep_deleted_kb_documents(db_session, running_job)

    scheduled = (
        await db_session.scalars(
            select(Job).where(
                Job.kind == "kb.sweep_deleted",
                Job.id != first.id,
                Job.id != running_job.id,
            )
        )
    ).all()
    assert len(scheduled) == 1
    assert scheduled[0].run_after > datetime.now(UTC)
