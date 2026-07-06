"""Tests for file extraction enqueueing and processing summaries."""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.files import FileRevision
from models.jobs import Job
from services.files import (
    confirm_file_upload,
    create_file_upload,
    edit_file,
    get_files_processing_summary,
    restore_file_revision,
)
from services.files.domain import (
    FileConfirmRequest,
    FileEditRequest,
    FileRestoreRequest,
    FileUploadRequest,
)
from services.files.utils import revision_object_key, sha256_hex
from services.storage.factory import get_storage_provider
from tests.factories import (
    build_file,
    build_file_revision,
    build_user,
    build_workspace,
    build_workspace_membership,
)
from tests.support.requests import build_test_request
from tests.support.storage import reset_storage_provider_cache

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


async def _workspace_context(db: AsyncSession):
    user = build_user(email=f"processing-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"processing-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    db.add_all([user, workspace, membership])
    await db.flush()
    return user, workspace, membership


async def test_confirm_ingestible_upload_sets_pending_and_enqueues_ids_only(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    grant_result = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="Report.pdf",
            content_type="application/pdf",
            size_bytes=8,
        ),
    )
    assert grant_result.grant is not None
    await get_storage_provider().put_object(
        grant_result.grant.upload.ref,
        b"%PDF-1.1",
        content_type="application/pdf",
    )

    confirmed = await confirm_file_upload(
        db_session,
        request=build_test_request(path="/api/v1/files/uploads/confirm"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileConfirmRequest(upload_token=grant_result.grant.upload_token),
    )

    assert confirmed.processing_status == "pending"
    revision = await db_session.scalar(
        select(FileRevision).where(FileRevision.id == confirmed.current_revision_id)
    )
    assert revision is not None
    job = await db_session.scalar(select(Job).where(Job.kind == "files.extract"))
    assert job is not None
    assert job.workspace_id == workspace.id
    assert job.subject_type == "file_revision"
    assert job.subject_id == revision.id
    assert job.payload == {"file_id": str(confirmed.id), "revision_id": str(revision.id)}
    assert job.content_hash == revision.content_hash
    assert job.initiated_by_user_id == actor.id
    assert job.max_attempts == 3

    double_confirmed = await confirm_file_upload(
        db_session,
        request=build_test_request(path="/api/v1/files/uploads/confirm"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileConfirmRequest(upload_token=grant_result.grant.upload_token),
    )
    assert double_confirmed.current_revision_id == confirmed.current_revision_id
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "files.extract")
        )
        == 1
    )


async def test_non_ingestible_confirm_and_text_edit_do_not_enqueue(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    grant_result = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="notes.txt",
            content_type="text/plain",
            size_bytes=5,
        ),
    )
    assert grant_result.grant is not None
    await get_storage_provider().put_object(
        grant_result.grant.upload.ref,
        b"hello",
        content_type="text/plain",
    )
    confirmed = await confirm_file_upload(
        db_session,
        request=build_test_request(path="/api/v1/files/uploads/confirm"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileConfirmRequest(upload_token=grant_result.grant.upload_token),
    )
    assert confirmed.processing_status == "ready"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "files.extract")
        )
        == 0
    )

    edited = await edit_file(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{confirmed.id}/content", method="PUT"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=confirmed.id,
        payload=FileEditRequest(
            content="updated",
            expected_current_revision_id=confirmed.current_revision_id,
        ),
    )

    assert edited.processing_status == "ready"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "files.extract")
        )
        == 0
    )


async def test_restore_ingestible_revision_enqueues_extraction(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    file = build_file(
        workspace=workspace,
        name="report.pdf",
        content_type="application/pdf",
        extension=".pdf",
        processing_status="ready",
    )
    db_session.add(file)
    await db_session.flush()
    source = build_file_revision(
        file,
        revision_number=1,
        created_by_user_id=actor.id,
        object_key=revision_object_key(workspace.id, file.id, uuid4(), ".pdf"),
    )
    current = build_file_revision(
        file,
        revision_number=2,
        revision_kind="replace",
        created_by_user_id=actor.id,
        content_hash="b" * 64,
        object_key=revision_object_key(workspace.id, file.id, uuid4(), ".pdf"),
    )
    db_session.add_all([source, current])
    await db_session.flush()
    file.current_revision_id = current.id
    file.revision_count = 2
    file.content_hash = current.content_hash
    await db_session.flush()

    restored = await restore_file_revision(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}/restore"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
        payload=FileRestoreRequest(
            revision_id=source.id,
            expected_current_revision_id=current.id,
        ),
    )

    assert restored.processing_status == "pending"
    job = await db_session.scalar(
        select(Job).where(
            Job.kind == "files.extract", Job.subject_id == restored.current_revision_id
        )
    )
    assert job is not None


async def test_files_processing_summary_counts_workspace_statuses_and_jobs(
    db_session: AsyncSession,
) -> None:
    _actor, workspace, _membership = await _workspace_context(db_session)
    other_workspace = build_workspace(slug=f"processing-other-{uuid4().hex[:8]}")
    db_session.add(other_workspace)
    await db_session.flush()
    for status in ("pending", "processing", "ready", "error"):
        db_session.add(build_file(workspace=workspace, processing_status=status))
    deleted = build_file(workspace=workspace, processing_status="error")
    deleted.soft_delete()
    db_session.add(deleted)
    db_session.add(build_file(workspace=other_workspace, processing_status="pending"))
    db_session.add(
        Job(
            kind="files.extract",
            workspace_id=workspace.id,
            status="running",
            payload={},
            content_hash=sha256_hex(b"running"),
        )
    )
    db_session.add(
        Job(
            kind="jobs.sweep_terminal",
            workspace_id=workspace.id,
            status="running",
            payload={},
            content_hash=sha256_hex(b"generic-running"),
        )
    )
    db_session.add(
        Job(
            kind="files.extract",
            workspace_id=other_workspace.id,
            status="pending",
            payload={},
            content_hash=sha256_hex(b"other-pending"),
        )
    )
    await db_session.flush()

    summary = await get_files_processing_summary(db_session, workspace=workspace)

    assert summary.pending == 1
    assert summary.processing == 1
    assert summary.ready == 1
    assert summary.error == 1
    assert summary.in_flight_jobs == 1
