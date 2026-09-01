"""Knowledge Base refreshable-source reconciliation tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import get_maintenance_async_db_session_factory
from core.settings import settings
from models.jobs import Job
from models.kb import KBDocument
from services.jobs.enqueue_job import enqueue_job
from services.jobs.handlers.reconcile_kb_sources import handle_reconcile_kb_sources
from services.kb.ensure_reconcile_job import (
    KB_RECONCILE_SOURCES_KIND,
    ensure_kb_reconcile_job,
)
from services.kb.reconcile_sources import reconcile_kb_sources
from tests.factories import build_job, build_kb_document, build_workspace

pytestmark = pytest.mark.asyncio


def _source_document(
    *,
    workspace,
    source_type: str,
    synced_at: datetime | None,
    sync_status: str = "ready",
) -> KBDocument:
    return build_kb_document(
        workspace=workspace,
        title=f"Refreshable source {uuid4().hex}",
        source_type=source_type,
        status="ready",
        external_id=uuid4().hex if source_type == "integration" else None,
        external_url="https://example.com/page" if source_type == "url" else None,
        source_sync_status=sync_status,
        source_synced_at=synced_at,
        content_md="# Imported\n\nProvider content.",
    )


async def test_reconcile_queues_one_global_bounded_batch_without_duplicates(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del db_session_factory
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    monkeypatch.setattr(settings, "KB_SOURCE_REFRESH_INTERVAL_SECONDS", 3_600)
    monkeypatch.setattr(settings, "KB_SOURCE_SCAN_BATCH_SIZE", 3)
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        workspace_a = build_workspace(slug=f"reconcile-a-{uuid4().hex[:8]}")
        workspace_b = build_workspace(slug=f"reconcile-b-{uuid4().hex[:8]}")
        db.add_all([workspace_a, workspace_b])
        await db.flush()
        never_synced = _source_document(
            workspace=workspace_b,
            source_type="url",
            synced_at=None,
        )
        oldest = _source_document(
            workspace=workspace_a,
            source_type="integration",
            synced_at=now - timedelta(hours=5),
        )
        second = _source_document(
            workspace=workspace_b,
            source_type="url",
            synced_at=now - timedelta(hours=4),
        )
        third = _source_document(
            workspace=workspace_a,
            source_type="integration",
            synced_at=now - timedelta(hours=3),
        )
        recent = _source_document(
            workspace=workspace_b,
            source_type="url",
            synced_at=now - timedelta(minutes=30),
        )
        pending = _source_document(
            workspace=workspace_a,
            source_type="url",
            synced_at=None,
            sync_status="pending",
        )
        db.add_all([never_synced, oldest, second, third, recent, pending])
        await db.flush()
        existing = await enqueue_job(
            db,
            kind="kb.ingest_document",
            workspace_id=workspace_a.id,
            subject_type="kb_document",
            subject_id=oldest.id,
            initiated_by_user_id=None,
        )

        assert await reconcile_kb_sources(db, now=now) == 3

        jobs = (
            await db.scalars(
                select(Job).where(Job.kind == "kb.ingest_document").order_by(Job.subject_id)
            )
        ).all()
        assert len(jobs) == 3
        assert {job.subject_id for job in jobs} == {never_synced.id, oldest.id, second.id}
        assert {job.workspace_id for job in jobs} == {workspace_a.id, workspace_b.id}
        assert next(job for job in jobs if job.subject_id == oldest.id).id == existing.id
        assert all(job.concurrency_user_id is None for job in jobs)
        assert all(job.initiated_by_user_id is None for job in jobs)
        assert all(job.payload == {} for job in jobs)


async def test_reconcile_advances_past_sources_checked_by_the_previous_batch(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del db_session_factory
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    monkeypatch.setattr(settings, "KB_SOURCE_REFRESH_INTERVAL_SECONDS", 3_600)
    monkeypatch.setattr(settings, "KB_SOURCE_SCAN_BATCH_SIZE", 2)
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        workspace = build_workspace(slug=f"reconcile-progress-{uuid4().hex[:8]}")
        db.add(workspace)
        await db.flush()
        first = _source_document(workspace=workspace, source_type="url", synced_at=None)
        second = _source_document(
            workspace=workspace,
            source_type="integration",
            synced_at=now - timedelta(hours=5),
        )
        third = _source_document(
            workspace=workspace,
            source_type="url",
            synced_at=now - timedelta(hours=4),
        )
        db.add_all([first, second, third])
        await db.flush()

        assert await reconcile_kb_sources(db, now=now) == 2

        first.source_synced_at = now
        second.source_synced_at = now
        await db.flush()

        assert await reconcile_kb_sources(db, now=now) == 1
        queued_ids = set(
            await db.scalars(select(Job.subject_id).where(Job.kind == "kb.ingest_document"))
        )
        assert queued_ids == {first.id, second.id, third.id}


async def test_reconcile_selects_no_content_or_chunks(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    del db_session_factory
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        statements: list[str] = []

        def capture_statement(_conn, _cursor, statement, _params, _context, _executemany):
            statements.append(statement.lower())

        bind = db.get_bind()
        event.listen(bind, "before_cursor_execute", capture_statement)
        try:
            assert await reconcile_kb_sources(db) == 0
        finally:
            event.remove(bind, "before_cursor_execute", capture_statement)

        assert statements
        assert all("content_md" not in statement for statement in statements)
        assert all("kb_chunks" not in statement for statement in statements)


async def test_reconcile_handler_reschedules_after_an_empty_scan(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del db_session_factory
    monkeypatch.setattr(settings, "KB_SOURCE_REFRESH_INTERVAL_SECONDS", 600)
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        running_job = build_job(
            kind=KB_RECONCILE_SOURCES_KIND,
            content_hash="reconcile-kb-sources:running",
            status="running",
        )
        db.add(running_job)
        await db.flush()
        before = datetime.now(UTC)

        await handle_reconcile_kb_sources(db, running_job)

        scheduled = await db.scalar(
            select(Job).where(
                Job.kind == KB_RECONCILE_SOURCES_KIND,
                Job.id != running_job.id,
            )
        )
        assert scheduled is not None
        assert scheduled.workspace_id is None
        assert scheduled.concurrency_user_id is None
        assert scheduled.content_hash == f"reconcile-kb-sources:{running_job.id}"
        assert scheduled.payload == {"scheduled_by_job_id": str(running_job.id)}
        assert scheduled.run_after >= before + timedelta(seconds=600)


async def test_ensure_reconcile_job_is_idempotent_and_ownerless(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    del db_session_factory
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        first = await ensure_kb_reconcile_job(db)
        second = await ensure_kb_reconcile_job(db)

        assert second.id == first.id
        assert first.workspace_id is None
        assert first.concurrency_user_id is None
        assert first.content_hash == "reconcile-kb-sources:ensure"
