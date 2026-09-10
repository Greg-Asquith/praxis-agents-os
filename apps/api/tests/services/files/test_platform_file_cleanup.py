"""Platform retention protects live content and retries failed storage effects."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from models.files import File, FileRevision, FileUpload
from models.jobs import Job
from models.kb import KBDocument
from services.jobs.handlers import (
    sweep_platform_file_uploads as uploads_module,
    sweep_platform_files as files_module,
)
from tests.factories import build_user

pytestmark = pytest.mark.asyncio


async def _file(db: AsyncSession, *, deleted: bool = True) -> tuple[File, FileRevision]:
    file = File(
        scope="platform",
        name="Policy.txt",
        category="document",
        content_type="text/plain",
        extension=".txt",
        deleted=deleted,
        deleted_at=datetime.now(UTC) - timedelta(days=31) if deleted else None,
    )
    db.add(file)
    await db.flush()
    revision_id = uuid4()
    revision = FileRevision(
        id=revision_id,
        scope="platform",
        file_id=file.id,
        revision_number=1,
        revision_kind="create",
        content_type="text/plain",
        extension=".txt",
        size_bytes=3,
        content_hash="abc",
        object_key=f"platform/files/{file.id}/{revision_id}.txt",
        created_by_system=True,
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    return file, revision


async def test_platform_cleanup_rejects_tenant_jobs(db_session: AsyncSession) -> None:
    for handler in (files_module.sweep_platform_files, uploads_module.sweep_platform_file_uploads):
        with pytest.raises(RuntimeError, match="maintenance"):
            await handler(db_session, Job(kind="unused"))
    async with maintenance_async_db_session() as db:
        with pytest.raises(RuntimeError, match="maintenance"):
            await files_module.sweep_platform_files(db, Job(workspace_id=uuid4()))
        with pytest.raises(RuntimeError, match="maintenance"):
            await uploads_module.sweep_platform_file_uploads(db, Job(concurrency_user_id=uuid4()))


async def test_platform_purge_bounds_revisions_and_preserves_live_kb_pin(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock()
    monkeypatch.setattr(files_module, "get_storage_provider", lambda: provider)
    monkeypatch.setattr(files_module, "_SWEEP_BATCH_SIZE", 1)
    async with maintenance_async_db_session() as db:
        pinned_file, pinned_revision = await _file(db)
        db.add(
            KBDocument(
                scope="platform",
                title="Policy",
                source_type="upload",
                annotation_enabled=False,
                file_revision_id=pinned_revision.id,
            )
        )
        file, revision = await _file(db)
        second = FileRevision(
            scope="platform",
            file_id=file.id,
            revision_number=2,
            revision_kind="restore",
            restored_from_revision_id=revision.id,
            content_type="text/plain",
            extension=".txt",
            size_bytes=3,
            content_hash="abc",
            object_key=revision.object_key,
            created_by_system=True,
        )
        db.add(second)
        await db.flush()
        file.current_revision_id = second.id
        await db.flush()
        await files_module.sweep_platform_files(db, Job(id=uuid4()))
        assert await db.get(File, pinned_file.id) is pinned_file
        assert await db.get(FileRevision, pinned_revision.id) is pinned_revision
        assert await db.get(FileRevision, second.id) is None
        assert await db.get(FileRevision, revision.id) is revision
        await files_module.sweep_platform_files(db, Job(id=uuid4()))
        assert await db.get(File, file.id) is None
        assert provider.delete_object.await_count == 4
        assert all(
            call.args[0].bucket.value == "platform_private"
            for call in provider.delete_object.await_args_list
        )


async def test_platform_purge_failure_keeps_revision_for_retry(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock()
    provider.delete_object.side_effect = OSError("storage unavailable")
    monkeypatch.setattr(files_module, "get_storage_provider", lambda: provider)
    async with maintenance_async_db_session() as db:
        file, revision = await _file(db)
        with pytest.raises(OSError):
            await files_module.sweep_platform_files(db, Job(id=uuid4()))
        assert await db.get(FileRevision, revision.id) is revision
        provider.delete_object.side_effect = None
        await files_module.sweep_platform_files(db, Job(id=uuid4()))
        assert await db.get(File, file.id) is None


async def test_platform_orphan_cleanup_preserves_referenced_bytes_and_retries(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock()
    monkeypatch.setattr(uploads_module, "get_storage_provider", lambda: provider)
    async with maintenance_async_db_session() as db:
        actor = build_user()
        db.add(actor)
        file, revision = await _file(db, deleted=False)
        await db.flush()
        upload = FileUpload(
            scope="platform",
            file_id=file.id,
            revision_id=revision.id,
            object_key=f"platform/uploads/files/{uuid4()}.txt",
            filename="Policy.txt",
            content_type="text/plain",
            declared_size_bytes=3,
            created_by_user_id=actor.id,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        orphan = FileUpload(
            scope="platform",
            file_id=uuid4(),
            revision_id=uuid4(),
            object_key=f"platform/uploads/files/{uuid4()}.txt",
            filename="Orphan.txt",
            content_type="text/plain",
            declared_size_bytes=3,
            created_by_user_id=actor.id,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db.add_all([upload, orphan])
        await db.flush()
        provider.delete_object.side_effect = OSError("storage unavailable")
        with pytest.raises(OSError):
            await uploads_module.sweep_platform_file_uploads(db, Job(id=uuid4()))
        assert await db.get(FileUpload, upload.id) is upload
        provider.delete_object.side_effect = None
        provider.delete_object.reset_mock()
        await uploads_module.sweep_platform_file_uploads(db, Job(id=uuid4()))
        keys = [call.args[0].key for call in provider.delete_object.await_args_list]
        assert revision.object_key not in keys
        assert upload.object_key in keys
        assert f"platform/files/{orphan.file_id}/{orphan.revision_id}.txt" in keys
        assert await db.scalar(select(FileUpload.id).where(FileUpload.id == orphan.id)) is None


async def test_workspace_sweepers_leave_platform_tombstones_and_grants(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.jobs.handlers.sweep_deleted_files import sweep_deleted_files
    from services.kb.sweep_deleted_documents import sweep_deleted_kb_documents

    provider = AsyncMock()
    monkeypatch.setattr(
        "services.jobs.handlers.sweep_deleted_files.get_storage_provider", lambda: provider
    )
    async with maintenance_async_db_session() as db:
        file, revision = await _file(db)
        actor = build_user()
        db.add(actor)
        await db.flush()
        upload = FileUpload(
            scope="platform",
            file_id=uuid4(),
            revision_id=uuid4(),
            object_key=f"platform/uploads/files/{uuid4()}.txt",
            filename="Expired.txt",
            content_type="text/plain",
            declared_size_bytes=3,
            created_by_user_id=actor.id,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        document = KBDocument(
            scope="platform",
            title="Policy",
            source_type="upload",
            annotation_enabled=False,
            file_revision_id=revision.id,
            deleted=True,
            deleted_at=datetime.now(UTC) - timedelta(days=31),
        )
        db.add_all([upload, document])
        await db.flush()
        await sweep_deleted_files(db, Job(id=uuid4()))
        await sweep_deleted_kb_documents(db)
        assert await db.get(File, file.id) is file
        assert await db.get(FileUpload, upload.id) is upload
        assert await db.get(KBDocument, document.id) is document
        provider.delete_object.assert_not_awaited()


async def test_platform_upload_cleanup_bounds_grants_and_ensures_jobs(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock()
    monkeypatch.setattr(uploads_module, "get_storage_provider", lambda: provider)
    monkeypatch.setattr(uploads_module, "_SWEEP_BATCH_SIZE", 1)
    async with maintenance_async_db_session() as db:
        actor = build_user()
        db.add(actor)
        await db.flush()
        grants = [
            FileUpload(
                scope="platform",
                file_id=uuid4(),
                revision_id=uuid4(),
                object_key=f"platform/uploads/files/{uuid4()}.txt",
                filename="Expired.txt",
                content_type="text/plain",
                declared_size_bytes=3,
                created_by_user_id=actor.id,
                expires_at=datetime.now(UTC) - timedelta(hours=1),
                consumed_at=datetime.now(UTC) if consumed else None,
            )
            for consumed in (True, False)
        ]
        db.add_all(grants)
        await db.flush()
        await uploads_module.sweep_platform_file_uploads(db, Job(id=uuid4()))
        remaining = list(
            (await db.scalars(select(FileUpload).where(FileUpload.scope == "platform"))).all()
        )
        assert len(remaining) == 1
        assert provider.delete_object.await_count == 2
        await files_module.ensure_platform_files_sweep_jobs(db)
        await files_module.ensure_platform_files_sweep_jobs(db)
        jobs = list(
            (
                await db.scalars(
                    select(Job).where(
                        Job.kind.in_(
                            [
                                files_module.SWEEP_PLATFORM_FILES_KIND,
                                uploads_module.SWEEP_PLATFORM_FILE_UPLOADS_KIND,
                            ]
                        )
                    )
                )
            ).all()
        )
        assert len(jobs) == 2


async def test_platform_purge_rechecks_pin_committed_during_revision_lock_wait(
    committed_db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock()
    monkeypatch.setattr(files_module, "get_storage_provider", lambda: provider)
    async with maintenance_async_db_session() as db:
        file, revision = await _file(db)
        file_id, revision_id = file.id, revision.id
    pin_id = uuid4()
    job_id = uuid4()
    sweep_started = asyncio.Event()
    sweep_pid = None

    async def sweep():
        nonlocal sweep_pid
        async with maintenance_async_db_session() as db:
            sweep_pid = await db.scalar(text("SELECT pg_backend_pid()"))
            sweep_started.set()
            await files_module.sweep_platform_files(db, Job(id=job_id))

    sweep_task = None
    try:
        async with asyncio.timeout(10):
            async with maintenance_async_db_session() as pin_db:
                await pin_db.scalar(
                    select(FileRevision).where(FileRevision.id == revision_id).with_for_update()
                )
                pin_db.add(
                    KBDocument(
                        id=pin_id,
                        scope="platform",
                        title="Policy",
                        source_type="upload",
                        annotation_enabled=False,
                        file_revision_id=revision_id,
                    )
                )
                await pin_db.flush()
                sweep_task = asyncio.create_task(sweep())
                await sweep_started.wait()
                async with maintenance_async_db_session() as observer:
                    while not await observer.scalar(  # noqa: ASYNC110
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": sweep_pid},
                    ):
                        await asyncio.sleep(0.01)
                assert not sweep_task.done()
                provider.delete_object.assert_not_awaited()
            await sweep_task
        async with maintenance_async_db_session() as db:
            assert await db.get(File, file_id) is not None
            assert await db.get(FileRevision, revision_id) is not None
            assert (await db.get(KBDocument, pin_id)).file_revision_id == revision_id
        provider.delete_object.assert_not_awaited()
    finally:
        if sweep_task is not None:
            if not sweep_task.done():
                sweep_task.cancel()
            await asyncio.gather(sweep_task, return_exceptions=True)
        async with maintenance_async_db_session() as db:
            await db.execute(delete(KBDocument).where(KBDocument.id == pin_id))
            source = await db.get(File, file_id)
            if source is not None:
                source.current_revision_id = None
                await db.flush()
                await db.execute(delete(FileRevision).where(FileRevision.file_id == file_id))
                await db.delete(source)
            await db.execute(delete(Job).where(Job.content_hash == f"platform-files:{job_id}"))


async def test_platform_purge_releases_deleted_knowledge_pin(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AsyncMock()
    monkeypatch.setattr(files_module, "get_storage_provider", lambda: provider)
    async with maintenance_async_db_session() as db:
        file, revision = await _file(db)
        document = KBDocument(
            scope="platform",
            title="Deleted policy",
            source_type="upload",
            annotation_enabled=False,
            file_revision_id=revision.id,
            deleted=True,
            deleted_at=datetime.now(UTC),
        )
        db.add(document)
        await db.flush()
        await files_module.sweep_platform_files(db, Job(id=uuid4()))
        assert await db.get(File, file.id) is None
        assert await db.get(FileRevision, revision.id) is None
        await db.refresh(document)
        assert document.file_revision_id is None
        assert document.deleted is True
        assert provider.delete_object.await_count == 2
