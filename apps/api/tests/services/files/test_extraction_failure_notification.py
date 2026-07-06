"""Tests for extraction failure notifications through the job harness."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import workers.job_runner as job_runner
from core.settings import settings
from models.files import File, FileRevision
from models.jobs import Job
from models.notification import Notification
from services.files.utils import private_ref_from_key, revision_object_key
from services.jobs.domain import JOB_STATUS_FAILED, JOB_STATUS_PENDING
from services.jobs.enqueue_job import enqueue_job
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache
from utils.document_markdown import DocumentConversionError

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def test_extraction_final_failure_notifies_only_after_attempts_exhaust(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.jobs.handlers.extract_file_markdown as extract_module

    async def fail_convert(*_args, **_kwargs):
        raise DocumentConversionError("permanent extraction failure")

    monkeypatch.setattr(extract_module, "convert_document_to_markdown", fail_convert)
    await _clear_jobs_and_notifications(committed_db_session_factory)
    async with committed_db_session_factory() as db:
        file, revision, user = await _persist_extractable_file(db)
        job = await enqueue_job(
            db,
            kind="files.extract",
            workspace_id=file.workspace_id,
            subject_type="file_revision",
            subject_id=revision.id,
            payload={"file_id": str(file.id), "revision_id": str(revision.id)},
            content_hash=revision.content_hash,
            max_attempts=2,
            initiated_by_user_id=user.id,
        )
        job_id = job.id
        await db.commit()

    await job_runner.run_once(owner_instance_id="extract-failure-test")
    async with committed_db_session_factory() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        assert job.status == JOB_STATUS_PENDING
        assert await db.scalar(select(Notification).where(Notification.source == "jobs")) is None
        job.run_after = datetime.now(UTC)
        await db.commit()

    await job_runner.run_once(owner_instance_id="extract-failure-test")
    async with committed_db_session_factory() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        assert job.status == JOB_STATUS_FAILED
        notes = (await db.scalars(select(Notification).where(Notification.source == "jobs"))).all()
        assert len(notes) == 1
        assert notes[0].recipient_user_id == user.id
        file = await db.get(File, file.id)
        assert file is not None
        assert file.processing_status == "error"

    await _clear_jobs_and_notifications(committed_db_session_factory)


async def _persist_extractable_file(db: AsyncSession) -> tuple[File, FileRevision, object]:
    workspace = build_workspace(slug=f"extract-notify-{uuid4().hex[:8]}")
    user = build_user(email=f"extract-notify-{uuid4().hex}@example.com")
    file = build_file(
        workspace=workspace,
        name="report.pdf",
        content_type="application/pdf",
        extension=".pdf",
        processing_status="pending",
    )
    db.add_all([workspace, user])
    await db.flush()
    db.add(file)
    await db.flush()
    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, ".pdf")
    await get_storage_provider().put_object(
        private_ref_from_key(object_key),
        b"%PDF-1.1",
        content_type="application/pdf",
    )
    revision = build_file_revision(
        file,
        revision_id=revision_id,
        object_key=object_key,
        content_type="application/pdf",
        extension=".pdf",
        created_by_user_id=user.id,
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    return file, revision, user


async def _clear_jobs_and_notifications(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as db:
        await db.execute(delete(Notification))
        await db.execute(delete(Job))
        await db.commit()
