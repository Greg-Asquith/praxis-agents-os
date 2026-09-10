"""Platform extraction checks ownership and live revisions before storing output."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.database import (
    get_async_db_session_factory,
    maintenance_async_db_session,
    set_session_tenant_context,
)
from core.exceptions.auth import AuthorizationError
from core.settings import settings
from models.files import File, FileRevision
from services.jobs.handlers import extract_platform_file_markdown as extraction
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_file_revision, build_job, build_user, build_workspace
from tests.support.storage import reset_storage_provider_cache
from utils.digests import sha256_hex

pytestmark = pytest.mark.asyncio


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "extraction-admin@example.com")
    reset_storage_provider_cache()
    yield
    reset_storage_provider_cache()


async def _draft():
    data = b"Platform guidance"
    file = build_file(workspace=build_workspace(), processing_status="pending")
    revision_id = uuid4()
    revision = build_file_revision(
        file,
        revision_id=revision_id,
        scope="platform",
        workspace_id=None,
        content_type="text/plain",
        size_bytes=len(data),
        content_hash=sha256_hex(data),
        object_key=f"platform/files/{file.id}/{revision_id}.txt",
    )
    file.scope, file.workspace_id = "platform", None
    actor = build_user(email="extraction-admin@example.com")
    async with maintenance_async_db_session() as db:
        db.add(actor)
        db.add(file)
        await db.flush()
        db.add(revision)
        await db.flush()
        file.current_revision_id = revision.id
        file.revision_count = 1
    await get_storage_provider().put_object(
        make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key), data
    )
    actor_id = actor.id
    job = build_job(
        kind="files.extract_platform",
        subject_type="file_revision",
        subject_id=revision.id,
        concurrency_user_id=actor_id,
        initiated_by_user_id=actor_id,
        content_hash=revision.content_hash,
        payload={"file_id": str(file.id), "revision_id": str(revision.id)},
    )
    return file, revision, job


async def _run(job):
    async with get_async_db_session_factory()() as db:
        await set_session_tenant_context(db, workspace_id=None, user_id=job.initiated_by_user_id)
        try:
            await extraction.extract_platform_file_markdown(db, job)
        finally:
            await db.commit()


async def test_platform_extraction_stores_immutable_markdown_once(
    db_session_factory, local_storage, monkeypatch
):
    file, revision, job = await _draft()
    await _run(job)
    async with maintenance_async_db_session() as db:
        stored = await db.get(FileRevision, revision.id)
        parent = await db.get(File, file.id)
        assert parent.processing_status == "ready"
        assert parent.processing_attempts == 1
        ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, stored.markdown_object_key)
        assert await get_storage_provider().get_object(ref) == b"Platform guidance"
    put = AsyncMock(side_effect=AssertionError("Extraction retry rewrote output"))
    monkeypatch.setattr(get_storage_provider(), "put_object", put)
    await _run(job)
    put.assert_not_awaited()


@pytest.mark.parametrize("change", ["deleted", "withdrawn", "changed", "stale"])
async def test_platform_extraction_rechecks_parent_after_conversion(
    db_session_factory, local_storage, monkeypatch, change
):
    file, revision, job = await _draft()
    original_convert = extraction.convert_document_to_markdown

    async def change_parent(*args, **kwargs):
        async with maintenance_async_db_session() as db:
            parent = await db.get(File, file.id)
            if change == "deleted":
                parent.soft_delete()
            elif change == "withdrawn":
                published = await db.get(FileRevision, revision.id)
                published.is_published = True
                await db.flush()
                parent.published_revision_id = revision.id
                parent.is_published = False
            elif change == "stale":
                parent.current_revision_id = None
            else:
                parent.updated_at += timedelta(seconds=1)
        return await original_convert(*args, **kwargs)

    monkeypatch.setattr(extraction, "convert_document_to_markdown", change_parent)
    put = AsyncMock()
    monkeypatch.setattr(get_storage_provider(), "put_object", put)
    await _run(job)
    put.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        stored = await db.get(FileRevision, revision.id)
        parent = await db.get(File, file.id)
        assert stored.markdown_object_key is None
        assert parent.processing_attempts == 0


@pytest.mark.parametrize("change", ["workspace", "subject", "owner", "payload"])
async def test_platform_extraction_rejects_malformed_jobs(monkeypatch, change):
    actor_id, revision_id = uuid4(), uuid4()
    job = build_job(
        subject_type="file_revision",
        subject_id=revision_id,
        concurrency_user_id=actor_id,
        initiated_by_user_id=actor_id,
        payload={"file_id": str(uuid4()), "revision_id": str(revision_id)},
    )
    if change == "workspace":
        job.workspace_id = uuid4()
    elif change == "subject":
        job.subject_id = uuid4()
    elif change == "owner":
        job.concurrency_user_id = uuid4()
    else:
        job.payload = {"file_id": "invalid"}
    maintenance = AsyncMock()
    monkeypatch.setattr(extraction, "maintenance_async_db_session", maintenance)
    with pytest.raises(ValueError):
        await extraction.extract_platform_file_markdown(AsyncMock(), job)
    maintenance.assert_not_called()


@pytest.mark.parametrize("failure", ["size", "hash", "conversion", "oversized_markdown"])
async def test_platform_extraction_failure_keeps_revision_unprocessed(
    db_session_factory, local_storage, monkeypatch, failure
):
    file, revision, job = await _draft()
    provider = get_storage_provider()
    if failure in {"size", "hash"}:
        await provider.put_object(
            make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
            b"x" * (revision.size_bytes + (failure == "size")),
        )
    else:
        convert = AsyncMock(side_effect=ValueError("Conversion failed"))
        if failure == "oversized_markdown":
            convert = AsyncMock(return_value="x" * (settings.FILES_MAX_MARKDOWN_BYTES + 1))
        monkeypatch.setattr(extraction, "convert_document_to_markdown", convert)
    put = AsyncMock()
    monkeypatch.setattr(provider, "put_object", put)
    with pytest.raises(ValueError):
        await _run(job)
    put.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        stored = await db.get(FileRevision, revision.id)
        parent = await db.get(File, file.id)
        assert stored.markdown_object_key is None
        assert parent.processing_status == "error"
        assert parent.processing_attempts == 1


@pytest.mark.parametrize("cancel", [False, True])
async def test_platform_extraction_cleans_output_after_interrupted_write(
    db_session_factory, local_storage, monkeypatch, cancel
):
    file, revision, job = await _draft()
    provider = get_storage_provider()
    original_put = provider.put_object
    written = []

    async def interrupted_put(ref, *args, **kwargs):
        assert kwargs["overwrite"] is False
        await original_put(ref, *args, **kwargs)
        written.append(ref)
        if cancel:
            raise asyncio.CancelledError()
        raise ValueError("Storage acknowledgement failed")

    monkeypatch.setattr(provider, "put_object", interrupted_put)
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        await _run(job)
    assert len(written) == 1
    assert await provider.stat_object(written[0]) is None
    async with maintenance_async_db_session() as db:
        stored = await db.get(FileRevision, revision.id)
        parent = await db.get(File, file.id)
        assert stored.markdown_object_key is None
        assert parent.processing_status == ("pending" if cancel else "error")


@pytest.mark.parametrize("state", ["ordinary", "inactive", "deleted", "missing"])
async def test_platform_extraction_requires_live_super_admin(monkeypatch, state):
    actor = build_user(email="extraction-admin@example.com", is_active=True)
    actor.deleted = False
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", actor.email)
    if state == "ordinary":
        actor.email = "ordinary@example.com"
    elif state == "inactive":
        actor.is_active = False
    elif state == "deleted":
        actor.deleted = True
    revision_id = uuid4()
    job = build_job(
        subject_type="file_revision",
        subject_id=revision_id,
        concurrency_user_id=actor.id,
        initiated_by_user_id=actor.id,
        payload={"file_id": str(uuid4()), "revision_id": str(revision_id)},
    )
    db = AsyncMock()
    db.get.return_value = None if state == "missing" else actor
    maintenance = AsyncMock()
    monkeypatch.setattr(extraction, "maintenance_async_db_session", maintenance)
    with pytest.raises(AuthorizationError):
        await extraction.extract_platform_file_markdown(db, job)
    maintenance.assert_not_called()


async def test_platform_extraction_recovers_untracked_immutable_output(
    db_session_factory, local_storage, monkeypatch
):
    file, revision, job = await _draft()
    provider = get_storage_provider()
    ref = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE,
        f"platform/files/{file.id}/{revision.id}.extracted.md",
    )
    await provider.put_object(ref, b"Platform guidance", content_type="text/markdown")
    put = AsyncMock(side_effect=AssertionError("Existing output was overwritten"))
    monkeypatch.setattr(provider, "put_object", put)
    await _run(job)
    put.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        stored = await db.get(FileRevision, revision.id)
        assert stored.markdown_object_key == ref.key


@pytest.mark.parametrize("failure", ["flush", "commit"])
async def test_platform_extraction_recovers_output_after_database_failure(
    db_session_factory, local_storage, monkeypatch, failure
):
    file, revision, job = await _draft()
    sessions = 0

    @asynccontextmanager
    async def fail_persistence_once():
        nonlocal sessions
        sessions += 1
        async with maintenance_async_db_session() as db:
            if sessions == 2:
                monkeypatch.setattr(
                    db, failure, AsyncMock(side_effect=RuntimeError("Database write failed"))
                )
            yield db

    monkeypatch.setattr(extraction, "maintenance_async_db_session", fail_persistence_once)
    with pytest.raises(RuntimeError, match="Database write failed"):
        await _run(job)
    provider = get_storage_provider()
    ref = make_storage_object_ref(
        StorageBucket.PLATFORM_PRIVATE,
        f"platform/files/{file.id}/{revision.id}.extracted.md",
    )
    assert await provider.get_object(ref) == b"Platform guidance"
    async with maintenance_async_db_session() as db:
        stored = await db.get(FileRevision, revision.id)
        parent = await db.get(File, file.id)
        assert stored.markdown_object_key is None
        assert parent.processing_status == "error"

    put = AsyncMock(side_effect=AssertionError("Retry overwrote immutable output"))
    monkeypatch.setattr(provider, "put_object", put)
    await _run(job)
    put.assert_not_awaited()
    async with maintenance_async_db_session() as db:
        stored = await db.get(FileRevision, revision.id)
        parent = await db.get(File, file.id)
        assert stored.markdown_object_key == ref.key
        assert parent.processing_status == "ready"


async def test_workspace_extraction_refuses_platform_job_before_queries():
    from services.jobs.handlers.extract_file_markdown import extract_file_markdown

    db = AsyncMock()
    job = build_job(
        workspace_id=None, payload={"file_id": str(uuid4()), "revision_id": str(uuid4())}
    )
    await extract_file_markdown(db, job)
    db.scalar.assert_not_awaited()
