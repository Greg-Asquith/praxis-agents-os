"""Service tests for workspace file upload and lifecycle operations."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError
from core.settings import settings
from models.audit_event import AuditEvent
from models.files import File, FileRevision, FileUpload
from models.jobs import Job
from models.workspace import WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
from services.files import (
    confirm_file_upload,
    create_file_upload,
    delete_file,
    edit_file,
    get_files_usage,
    list_files,
    purge_file,
    restore_file_revision,
)
from services.files.contract import contract_for_content_type
from services.files.domain import (
    FileConfirmRequest,
    FileEditRequest,
    FileRestoreRequest,
    FileUploadRequest,
)
from services.files.utils import private_ref_from_key, revision_object_key, sha256_hex
from services.jobs.handlers.sweep_deleted_files import ensure_files_sweep_job, sweep_deleted_files
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


async def _workspace_context(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.MEMBER,
):
    user = build_user(email=f"file-user-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"files-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    return user, workspace, membership


async def _persist_file(
    db: AsyncSession,
    *,
    workspace,
    actor,
    filename: str = "notes.txt",
    content_type: str = "text/plain",
    content: bytes = b"hello",
):
    entry = contract_for_content_type(content_type)
    content_hash = sha256_hex(content)
    file = build_file(
        workspace=workspace,
        name=filename,
        category=entry.category.value,
        content_type=entry.content_type,
        extension=entry.extensions[0],
        size_bytes=len(content),
        content_hash=content_hash,
    )
    db.add(file)
    await db.flush()
    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file.id, revision_id, entry.extensions[0])
    await get_storage_provider().put_object(
        private_ref_from_key(object_key),
        content,
        content_type=entry.content_type,
    )
    revision = build_file_revision(
        file,
        revision_id=revision_id,
        revision_number=1,
        revision_kind="create",
        created_by_user_id=actor.id,
        object_key=object_key,
        size_bytes=len(content),
        content_hash=content_hash,
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    return file, revision


async def test_create_file_upload_validates_metadata_deduplicates_and_flags_soft_limit(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    existing_file, _revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content=b"dedup",
    )

    with pytest.raises(AppValidationError):
        await create_file_upload(
            db_session,
            actor=actor,
            workspace=workspace,
            membership=membership,
            payload=FileUploadRequest(
                filename="wrong.docx",
                content_type="application/pdf",
                size_bytes=10,
            ),
        )

    deduped = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="same.txt",
            content_type="text/plain",
            size_bytes=5,
            content_hash=existing_file.content_hash,
        ),
    )
    assert deduped.deduplicated is True
    assert deduped.file is not None
    assert deduped.file.id == existing_file.id
    assert await db_session.scalar(select(func.count()).select_from(FileUpload)) == 0

    monkeypatch.setattr(settings, "FILES_WORKSPACE_STORAGE_SOFT_LIMIT_BYTES", 1)
    grant_result = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="fresh.txt",
            content_type="text/plain",
            size_bytes=5,
            allow_duplicate_content=True,
        ),
    )
    assert grant_result.grant is not None
    assert grant_result.grant.over_soft_limit is True
    upload = await db_session.scalar(select(FileUpload).where(FileUpload.file_id == grant_result.grant.file_id))
    assert upload is not None
    assert upload.object_key.endswith(".txt")

    _reader, _workspace, read_only_membership = await _workspace_context(
        db_session,
        role=WorkspaceRole.READ_ONLY,
    )
    with pytest.raises(AuthorizationError):
        await create_file_upload(
            db_session,
            actor=actor,
            workspace=workspace,
            membership=read_only_membership,
            payload=FileUploadRequest(
                filename="blocked.txt",
                content_type="text/plain",
                size_bytes=5,
            ),
        )


async def test_confirm_file_upload_computes_hash_is_idempotent_and_replaces(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    provider = get_storage_provider()
    grant_result = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="Report.md",
            content_type="text/markdown",
            size_bytes=12,
            content_hash="0" * 64,
        ),
    )
    assert grant_result.grant is not None
    await provider.put_object(
        grant_result.grant.upload.ref,
        b"# Real data\n",
        content_type="text/markdown",
    )

    confirmed = await confirm_file_upload(
        db_session,
        request=build_test_request(path="/api/v1/files/uploads/confirm"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileConfirmRequest(upload_token=grant_result.grant.upload_token),
    )

    assert confirmed.name == "Report.md"
    assert confirmed.content_hash == sha256_hex(b"# Real data\n")
    assert confirmed.processing_status == "ready"
    revision_count = await db_session.scalar(
        select(func.count()).select_from(FileRevision).where(FileRevision.file_id == confirmed.id)
    )
    assert revision_count == 1

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
            select(func.count()).select_from(FileRevision).where(FileRevision.file_id == confirmed.id)
        )
        == 1
    )

    replace_grant = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="Report.markdown",
            content_type="text/markdown",
            size_bytes=9,
            file_id=confirmed.id,
            allow_duplicate_content=True,
        ),
    )
    assert replace_grant.grant is not None
    await provider.put_object(
        replace_grant.grant.upload.ref,
        b"# Replace",
        content_type="text/markdown",
    )
    replaced = await confirm_file_upload(
        db_session,
        request=build_test_request(path="/api/v1/files/uploads/confirm"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileConfirmRequest(upload_token=replace_grant.grant.upload_token),
    )
    assert replaced.revision_count == 2
    latest = await db_session.scalar(
        select(FileRevision).where(FileRevision.id == replaced.current_revision_id)
    )
    assert latest is not None
    assert latest.revision_kind == "replace"

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.CREATE.value,
            AuditEvent.resource_type == AuditResourceType.FILE.value,
            AuditEvent.resource_id == str(confirmed.id),
        )
    )
    assert audit_event is not None
    assert audit_event.details["content_hash"] == confirmed.content_hash


async def test_confirm_preserves_extension_alias_and_rejects_deleted_replace(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    provider = get_storage_provider()

    grant_result = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="Report.markdown",
            content_type="text/markdown",
            size_bytes=8,
        ),
    )
    assert grant_result.grant is not None
    assert grant_result.grant.upload.ref.key.endswith(".markdown")
    await provider.put_object(
        grant_result.grant.upload.ref,
        b"# Alias",
        content_type="text/markdown",
    )

    confirmed = await confirm_file_upload(
        db_session,
        request=build_test_request(path="/api/v1/files/uploads/confirm"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileConfirmRequest(upload_token=grant_result.grant.upload_token),
    )

    assert confirmed.extension == ".markdown"
    revision = await db_session.scalar(
        select(FileRevision).where(FileRevision.id == confirmed.current_revision_id)
    )
    assert revision is not None
    assert revision.extension == ".markdown"
    assert revision.object_key.endswith(".markdown")

    replace_grant = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="Report.markdown",
            content_type="text/markdown",
            size_bytes=9,
            file_id=confirmed.id,
            allow_duplicate_content=True,
        ),
    )
    assert replace_grant.grant is not None
    await provider.put_object(
        replace_grant.grant.upload.ref,
        b"# Deleted",
        content_type="text/markdown",
    )
    await delete_file(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{confirmed.id}", method="DELETE"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=confirmed.id,
    )

    with pytest.raises(AppValidationError):
        await confirm_file_upload(
            db_session,
            request=build_test_request(path="/api/v1/files/uploads/confirm"),
            actor=actor,
            workspace=workspace,
            membership=membership,
            payload=FileConfirmRequest(upload_token=replace_grant.grant.upload_token),
        )


async def test_confirm_rejects_bad_stored_metadata_and_wrong_actor_token(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    provider = get_storage_provider()
    grant_result = await create_file_upload(
        db_session,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=FileUploadRequest(
            filename="bad.txt",
            content_type="text/plain",
            size_bytes=5,
        ),
    )
    assert grant_result.grant is not None
    await provider.put_object(
        grant_result.grant.upload.ref,
        b"bad",
        content_type="text/markdown",
    )

    with pytest.raises(AppValidationError):
        await confirm_file_upload(
            db_session,
            request=build_test_request(path="/api/v1/files/uploads/confirm"),
            actor=actor,
            workspace=workspace,
            membership=membership,
            payload=FileConfirmRequest(upload_token=grant_result.grant.upload_token),
        )

    other_actor = build_user(email=f"file-other-{uuid4().hex}@example.com")
    other_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=other_actor.id,
        role=WorkspaceRole.MEMBER,
    )
    db_session.add_all([other_actor, other_membership])
    await db_session.flush()

    with pytest.raises(AuthorizationError):
        await confirm_file_upload(
            db_session,
            request=build_test_request(path="/api/v1/files/uploads/confirm"),
            actor=other_actor,
            workspace=workspace,
            membership=other_membership,
            payload=FileConfirmRequest(upload_token=grant_result.grant.upload_token),
        )


async def test_edit_and_restore_are_append_only_and_conflict_on_stale_revision(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    file, original = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content=b"first",
    )

    edited = await edit_file(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}/content", method="PUT"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
        payload=FileEditRequest(
            content="second",
            expected_current_revision_id=original.id,
        ),
    )
    assert edited.revision_count == 2
    assert edited.content_hash == sha256_hex(b"second")

    with pytest.raises(ConflictError) as conflict:
        await edit_file(
            db_session,
            request=build_test_request(path=f"/api/v1/files/{file.id}/content", method="PUT"),
            actor=actor,
            workspace=workspace,
            membership=membership,
            file_id=file.id,
            payload=FileEditRequest(
                content="stale",
                expected_current_revision_id=original.id,
            ),
        )
    assert conflict.value.details["current_revision_id"] == str(edited.current_revision_id)

    restored = await restore_file_revision(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}/restore"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
        payload=FileRestoreRequest(
            revision_id=original.id,
            expected_current_revision_id=edited.current_revision_id,
        ),
    )
    assert restored.revision_count == 3
    restore_revision = await db_session.scalar(
        select(FileRevision).where(FileRevision.id == restored.current_revision_id)
    )
    assert restore_revision is not None
    assert restore_revision.revision_kind == "restore"
    assert restore_revision.restored_from_revision_id == original.id
    assert restore_revision.object_key == original.object_key
    assert restored.content_hash == original.content_hash


async def test_edit_and_restore_reject_invalid_file_states(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, workspace, membership = await _workspace_context(db_session)
    pdf_file, pdf_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        filename="report.pdf",
        content_type="application/pdf",
        content=b"%PDF",
    )
    with pytest.raises(AppValidationError):
        await edit_file(
            db_session,
            request=build_test_request(path=f"/api/v1/files/{pdf_file.id}/content", method="PUT"),
            actor=actor,
            workspace=workspace,
            membership=membership,
            file_id=pdf_file.id,
            payload=FileEditRequest(
                content="blocked",
                expected_current_revision_id=pdf_revision.id,
            ),
        )

    file, original = await _persist_file(db_session, workspace=workspace, actor=actor)
    monkeypatch.setattr(settings, "FILES_MAX_TEXT_EDIT_BYTES", 3)
    with pytest.raises(AppValidationError):
        await edit_file(
            db_session,
            request=build_test_request(path=f"/api/v1/files/{file.id}/content", method="PUT"),
            actor=actor,
            workspace=workspace,
            membership=membership,
            file_id=file.id,
            payload=FileEditRequest(
                content="four",
                expected_current_revision_id=original.id,
            ),
        )
    monkeypatch.setattr(settings, "FILES_MAX_TEXT_EDIT_BYTES", 2_097_152)

    edited = await edit_file(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}/content", method="PUT"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
        payload=FileEditRequest(content="second", expected_current_revision_id=original.id),
    )

    with pytest.raises(AppValidationError):
        await restore_file_revision(
            db_session,
            request=build_test_request(path=f"/api/v1/files/{file.id}/restore"),
            actor=actor,
            workspace=workspace,
            membership=membership,
            file_id=file.id,
            payload=FileRestoreRequest(
                revision_id=edited.current_revision_id,
                expected_current_revision_id=edited.current_revision_id,
            ),
        )
    with pytest.raises(ConflictError):
        await restore_file_revision(
            db_session,
            request=build_test_request(path=f"/api/v1/files/{file.id}/restore"),
            actor=actor,
            workspace=workspace,
            membership=membership,
            file_id=file.id,
            payload=FileRestoreRequest(
                revision_id=original.id,
                expected_current_revision_id=original.id,
            ),
        )


async def test_delete_purge_and_usage_handle_retained_and_shared_blobs(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, membership = await _workspace_context(
        db_session,
        role=WorkspaceRole.ADMIN,
    )
    file, original = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        content=b"first",
    )
    edited = await edit_file(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}/content", method="PUT"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
        payload=FileEditRequest(content="second", expected_current_revision_id=original.id),
    )
    await restore_file_revision(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}/restore"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
        payload=FileRestoreRequest(
            revision_id=original.id,
            expected_current_revision_id=edited.current_revision_id,
        ),
    )
    markdown_key = revision_object_key(workspace.id, file.id, uuid4(), ".md")
    await get_storage_provider().put_object(
        private_ref_from_key(markdown_key),
        b"markdown",
        content_type="text/markdown",
    )
    original.markdown_object_key = markdown_key
    original.markdown_size_bytes = len(b"markdown")
    await db_session.flush()
    usage_before_delete = await get_files_usage(db_session, workspace=workspace)
    assert usage_before_delete.used_bytes == len(b"first") + len(b"second") + len(b"markdown")

    await delete_file(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}", method="DELETE"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
    )
    listed = await list_files(db_session, workspace=workspace)
    assert listed.total == 0
    usage_after_soft_delete = await get_files_usage(db_session, workspace=workspace)
    assert usage_after_soft_delete.used_bytes == usage_before_delete.used_bytes

    provider = get_storage_provider()
    revisions = (
        await db_session.scalars(select(FileRevision).where(FileRevision.file_id == file.id))
    ).all()
    assert len(revisions) == 3
    for revision in revisions:
        assert await provider.stat_object(private_ref_from_key(revision.object_key)) is not None

    member_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.MEMBER,
    )
    with pytest.raises(AuthorizationError):
        await purge_file(
            db_session,
            request=build_test_request(path=f"/api/v1/files/{file.id}/purge"),
            actor=actor,
            workspace=workspace,
            membership=member_membership,
            file_id=file.id,
        )

    await purge_file(
        db_session,
        request=build_test_request(path=f"/api/v1/files/{file.id}/purge"),
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file.id,
    )
    assert await db_session.get(File, file.id) is None
    for revision in revisions:
        assert await provider.stat_object(private_ref_from_key(revision.object_key)) is None
    assert await provider.stat_object(private_ref_from_key(markdown_key)) is None


async def test_sweep_deleted_files_purges_expired_rows_and_abandoned_uploads(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor, workspace, _membership = await _workspace_context(db_session, role=WorkspaceRole.ADMIN)
    file, revision = await _persist_file(db_session, workspace=workspace, actor=actor)
    file.soft_delete(deleted_by=actor.id)
    file.deleted_at = datetime.now(UTC) - timedelta(days=31)
    retained_file, retained_revision = await _persist_file(
        db_session,
        workspace=workspace,
        actor=actor,
        filename="retained.txt",
        content=b"retained",
    )
    retained_file.soft_delete(deleted_by=actor.id)
    retained_file.deleted_at = datetime.now(UTC) - timedelta(days=29)

    provider = get_storage_provider()
    upload_ref_key = revision_object_key(workspace.id, uuid4(), uuid4(), ".txt")
    await provider.put_object(private_ref_from_key(upload_ref_key), b"stale", content_type="text/plain")
    upload = FileUpload(
        workspace_id=workspace.id,
        file_id=uuid4(),
        revision_id=uuid4(),
        object_key=upload_ref_key,
        filename="stale.txt",
        content_type="text/plain",
        declared_size_bytes=5,
        declared_content_hash=None,
        created_by_user_id=actor.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    consumed_ref_key = revision_object_key(workspace.id, uuid4(), uuid4(), ".txt")
    await provider.put_object(
        private_ref_from_key(consumed_ref_key),
        b"consumed",
        content_type="text/plain",
    )
    consumed_upload = FileUpload(
        workspace_id=workspace.id,
        file_id=uuid4(),
        revision_id=uuid4(),
        object_key=consumed_ref_key,
        filename="consumed.txt",
        content_type="text/plain",
        declared_size_bytes=8,
        declared_content_hash=None,
        created_by_user_id=actor.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
        consumed_at=datetime.now(UTC),
    )
    pending_ref_key = revision_object_key(workspace.id, uuid4(), uuid4(), ".txt")
    await provider.put_object(
        private_ref_from_key(pending_ref_key),
        b"pending",
        content_type="text/plain",
    )
    pending_upload = FileUpload(
        workspace_id=workspace.id,
        file_id=uuid4(),
        revision_id=uuid4(),
        object_key=pending_ref_key,
        filename="pending.txt",
        content_type="text/plain",
        declared_size_bytes=7,
        declared_content_hash=None,
        created_by_user_id=actor.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    job = Job(kind="files.sweep_deleted", content_hash=f"test-sweep-{uuid4()}")
    db_session.add_all([upload, consumed_upload, pending_upload, job])
    await db_session.flush()

    await sweep_deleted_files(db_session, job)

    assert await db_session.get(File, file.id) is None
    assert await provider.stat_object(private_ref_from_key(revision.object_key)) is None
    assert await db_session.get(File, retained_file.id) is not None
    assert await provider.stat_object(private_ref_from_key(retained_revision.object_key)) is not None
    assert await db_session.get(FileUpload, upload.id) is None
    assert await provider.stat_object(private_ref_from_key(upload_ref_key)) is None
    assert await db_session.get(FileUpload, consumed_upload.id) is not None
    assert await provider.stat_object(private_ref_from_key(consumed_ref_key)) is not None
    assert await db_session.get(FileUpload, pending_upload.id) is not None
    assert await provider.stat_object(private_ref_from_key(pending_ref_key)) is not None

    first = await ensure_files_sweep_job(db_session)
    second = await ensure_files_sweep_job(db_session)
    assert first.id == second.id
