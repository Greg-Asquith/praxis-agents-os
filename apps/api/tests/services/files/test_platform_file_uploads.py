"""Platform upload authority, capability binding, and atomic confirmation."""

import importlib
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.audit_event import AuditEvent
from models.files import File, FileRevision, FileUpload
from models.workspace import WorkspaceRole
from services.files import confirm_file_upload, create_file_upload, get_files_usage
from services.files.domain import FileConfirmRequest, FileUploadRequest
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request
from tests.support.storage import reset_storage_provider_cache
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def upload_context(db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    email = f"platform-admin-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)
    reset_storage_provider_cache()
    async with maintenance_async_db_session() as db:
        actor, workspace = build_user(email=email), build_workspace()
        membership = build_workspace_membership(
            workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.READ_ONLY
        )
        db.add_all([actor, workspace, membership])
    try:
        yield {"actor": actor, "workspace": workspace, "membership": membership}
    finally:
        reset_storage_provider_cache()


async def _grant(db, context, *, size=5, file_id=None):
    result = await create_file_upload(
        db,
        **context,
        scope=ContentScope.PLATFORM,
        payload=FileUploadRequest(
            filename="shared.txt", content_type="text/plain", size_bytes=size, file_id=file_id
        ),
    )
    assert result.grant is not None
    return result.grant


async def _confirm(db, context, token):
    return await confirm_file_upload(
        db,
        **context,
        scope=ContentScope.PLATFORM,
        request=build_test_request(),
        payload=FileConfirmRequest(upload_token=token),
    )


@pytest.mark.parametrize("operation", ["create", "confirm"])
async def test_non_admin_is_rejected_before_maintenance(monkeypatch, operation):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    actor, workspace = build_user(email="member@example.com"), build_workspace()
    context = {
        "actor": actor,
        "workspace": workspace,
        "membership": build_workspace_membership(workspace_id=workspace.id, user_id=actor.id),
    }
    module = importlib.import_module(f"services.files.{operation}_file_upload")
    maintenance = Mock(side_effect=AssertionError("maintenance must remain closed"))
    monkeypatch.setattr(module, "maintenance_async_db_session", maintenance)
    db = AsyncMock(spec=AsyncSession)
    with pytest.raises(AuthorizationError):
        if operation == "create":
            await _grant(db, context)
        else:
            await _confirm(db, context, "invalid")
    maintenance.assert_not_called()
    db.commit.assert_not_awaited()


async def test_read_only_admin_upload_is_platform_scoped_and_replay_safe(
    db_session, upload_context
):
    first = await _grant(db_session, upload_context)
    second = await _grant(db_session, upload_context)
    assert first.upload.ref.bucket == StorageBucket.PLATFORM_PRIVATE
    assert first.upload.ref.key.startswith("platform/uploads/files/")
    assert first.upload.ref.key != second.upload.ref.key
    assert first.over_soft_limit is False
    claims = jwt.decode(
        first.upload_token, settings.SECRET_KEY.get_secret_value(), algorithms=["HS256"]
    )
    async with maintenance_async_db_session() as db:
        upload = await db.scalar(select(FileUpload).where(FileUpload.file_id == first.file_id))
        assert upload.scope == ContentScope.PLATFORM
        assert upload.workspace_id is None
        assert upload.created_by_user_id == upload_context["actor"].id
        assert claims["jti"] == str(upload.id)
        assert claims["workspace_id"] is None
        assert claims["kind"] == "platform_file"
    provider = get_storage_provider()
    await provider.put_object(first.upload.ref, b"hello", content_type="text/plain")
    confirmed = await _confirm(db_session, upload_context, first.upload_token)
    replayed = await _confirm(db_session, upload_context, first.upload_token)
    assert confirmed.scope == ContentScope.PLATFORM
    assert confirmed.workspace_id is None
    assert confirmed.is_published is False
    assert replayed.current_revision_id == confirmed.current_revision_id
    async with maintenance_async_db_session() as db:
        revisions = (
            await db.scalars(select(FileRevision).where(FileRevision.file_id == confirmed.id))
        ).all()
        assert len(revisions) == 1
        revision = revisions[0]
        assert revision.scope == ContentScope.PLATFORM
        assert revision.workspace_id is None
        assert revision.object_key.startswith(f"platform/files/{confirmed.id}/")
        assert revision.object_key != first.upload.ref.key
        assert (
            await provider.get_object(
                make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key)
            )
            == b"hello"
        )
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(confirmed.id)))
        ).all()
        assert len(events) == 1
        assert events[0].workspace_id is None
        assert events[0].details["operation"] == "create"
        assert (await get_files_usage(db, workspace=upload_context["workspace"])).used_bytes == 0


@pytest.mark.parametrize(
    "field", ["actor_user_id", "object_key", "bucket", "kind", "workspace_id", "jti", "invalid_jti"]
)
async def test_confirmation_rejects_swapped_capability(db_session, upload_context, field):
    grant = await _grant(db_session, upload_context)
    other = await _grant(db_session, upload_context)
    claims = jwt.decode(
        grant.upload_token, settings.SECRET_KEY.get_secret_value(), algorithms=["HS256"]
    )
    other_claims = jwt.decode(
        other.upload_token, settings.SECRET_KEY.get_secret_value(), algorithms=["HS256"]
    )
    claims["jti" if field == "invalid_jti" else field] = {
        "actor_user_id": str(uuid4()),
        "object_key": other.upload.ref.key,
        "bucket": "private",
        "kind": "workspace_file",
        "workspace_id": str(upload_context["workspace"].id),
        "jti": other_claims["jti"],
        "invalid_jti": "non-uuid-token-id",
    }[field]
    token = jwt.encode(claims, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")
    with pytest.raises((AuthorizationError, AppValidationError)):
        await _confirm(db_session, upload_context, token)
    async with maintenance_async_db_session() as db:
        assert await db.get(File, grant.file_id) is None
        upload = await db.scalar(select(FileUpload).where(FileUpload.file_id == grant.file_id))
        assert upload.consumed_at is None


@pytest.mark.parametrize("content", [b"four", b"longer"])
async def test_confirmation_requires_exact_declared_size(db_session, upload_context, content):
    grant = await _grant(db_session, upload_context)
    await get_storage_provider().put_object(grant.upload.ref, content, content_type="text/plain")
    with pytest.raises(AppValidationError, match="declared size"):
        await _confirm(db_session, upload_context, grant.upload_token)
    async with maintenance_async_db_session() as db:
        assert await db.get(File, grant.file_id) is None


async def test_audit_failure_rolls_back_rows_and_confirmation_recovers_promoted_bytes(
    db_session, upload_context, monkeypatch
):
    grant = await _grant(db_session, upload_context)
    provider = get_storage_provider()
    await provider.put_object(grant.upload.ref, b"hello", content_type="text/plain")
    module = importlib.import_module("services.files.confirm_file_upload")
    with monkeypatch.context() as patch:
        patch.setattr(
            module,
            "record_platform_content_audit_event",
            AsyncMock(side_effect=RuntimeError("audit unavailable")),
        )
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await _confirm(db_session, upload_context, grant.upload_token)
    async with maintenance_async_db_session() as db:
        assert await db.get(File, grant.file_id) is None
        assert (
            await db.scalar(
                select(func.count())
                .select_from(FileRevision)
                .where(FileRevision.file_id == grant.file_id)
            )
            == 0
        )
        upload = await db.scalar(select(FileUpload).where(FileUpload.file_id == grant.file_id))
        assert upload.consumed_at is None
    assert await provider.stat_object(grant.upload.ref) is None
    recovered = await _confirm(db_session, upload_context, grant.upload_token)
    assert recovered.revision_count == 1
    assert recovered.size_bytes == 5


async def test_confirmation_does_not_overwrite_existing_destination(db_session, upload_context):
    grant = await _grant(db_session, upload_context)
    async with maintenance_async_db_session() as db:
        upload = await db.scalar(select(FileUpload).where(FileUpload.file_id == grant.file_id))
        final_ref = make_storage_object_ref(
            StorageBucket.PLATFORM_PRIVATE,
            f"platform/files/{upload.file_id}/{upload.revision_id}.txt",
        )
    provider = get_storage_provider()
    await provider.put_object(final_ref, b"other", content_type="text/plain")
    await provider.put_object(grant.upload.ref, b"hello", content_type="text/plain")
    with pytest.raises(ConflictError):
        await _confirm(db_session, upload_context, grant.upload_token)
    assert await provider.get_object(final_ref) == b"other"
    async with maintenance_async_db_session() as db:
        assert await db.get(File, grant.file_id) is None


async def test_platform_upload_cannot_replace_workspace_file(db_session, upload_context):
    async with maintenance_async_db_session() as db:
        file = build_file(workspace=upload_context["workspace"])
        db.add(file)
    with pytest.raises(NotFoundError):
        await _grant(db_session, upload_context, file_id=file.id)


async def test_confirmation_checks_persisted_upload_creator(db_session, upload_context):
    grant = await _grant(db_session, upload_context)
    async with maintenance_async_db_session() as db:
        other = build_user()
        db.add(other)
        await db.flush()
        upload = await db.scalar(select(FileUpload).where(FileUpload.file_id == grant.file_id))
        upload.created_by_user_id = other.id
    with pytest.raises(AppValidationError):
        await _confirm(db_session, upload_context, grant.upload_token)
    async with maintenance_async_db_session() as db:
        assert await db.get(File, grant.file_id) is None


async def test_pdf_upload_enqueues_platform_extraction(db_session, upload_context):
    from models.jobs import Job
    from services.jobs.registry import get_job_handler
    from services.runtime_catalogs import assemble_runtime_catalogs

    assemble_runtime_catalogs()
    assert get_job_handler("files.extract_platform") is not None
    content = b"%PDF-1.4\nplatform document"
    result = await create_file_upload(
        db_session,
        **upload_context,
        scope=ContentScope.PLATFORM,
        payload=FileUploadRequest(
            filename="shared.pdf", content_type="application/pdf", size_bytes=len(content)
        ),
    )
    grant = result.grant
    assert grant is not None
    await get_storage_provider().put_object(
        grant.upload.ref, content, content_type="application/pdf"
    )
    confirmed = await _confirm(db_session, upload_context, grant.upload_token)
    assert confirmed.processing_status == "pending"
    assert confirmed.is_published is False
    async with maintenance_async_db_session() as db:
        job = await db.scalar(select(Job).where(Job.subject_id == confirmed.current_revision_id))
        assert job is not None
        assert job.kind == "files.extract_platform"
        assert job.workspace_id is None
        assert job.concurrency_user_id == upload_context["actor"].id
        assert job.initiated_by_user_id == upload_context["actor"].id
        assert job.subject_type == "file_revision"
        assert job.content_hash == confirmed.content_hash
        assert job.status == "pending"
        assert job.payload == {
            "file_id": str(confirmed.id),
            "revision_id": str(confirmed.current_revision_id),
        }


async def test_platform_replacement_preserves_published_revision(db_session, upload_context):
    provider = get_storage_provider()
    first_grant = await _grant(db_session, upload_context)
    await provider.put_object(first_grant.upload.ref, b"hello", content_type="text/plain")
    first = await _confirm(db_session, upload_context, first_grant.upload_token)
    async with maintenance_async_db_session() as db:
        file = await db.get(File, first.id)
        revision = await db.get(FileRevision, first.current_revision_id)
        revision.is_published = True
        await db.flush()
        file.is_published = True
        file.published_revision_id = revision.id
    replacement_grant = await _grant(db_session, upload_context, size=7, file_id=first.id)
    await provider.put_object(replacement_grant.upload.ref, b"updated", content_type="text/plain")
    replacement = await _confirm(db_session, upload_context, replacement_grant.upload_token)
    assert replacement.revision_count == 2
    assert replacement.is_published is True
    assert replacement.current_revision_id != first.current_revision_id
    assert replacement.content_hash != first.content_hash
    async with maintenance_async_db_session() as db:
        file = await db.get(File, first.id)
        original = await db.get(FileRevision, first.current_revision_id)
        draft = await db.get(FileRevision, replacement.current_revision_id)
        assert file.published_revision_id == original.id
        assert file.is_published is True
        assert original.is_published is True
        assert original.size_bytes == 5
        assert original.content_hash == first.content_hash
        assert draft.is_published is False
        assert draft.revision_kind == "replace"
        assert draft.revision_number == 2
        assert draft.scope == ContentScope.PLATFORM
        assert draft.workspace_id is None
        assert file.size_bytes == draft.size_bytes == 7
        assert (
            await provider.get_object(
                make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, original.object_key)
            )
            == b"hello"
        )
        assert (
            await provider.get_object(
                make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, draft.object_key)
            )
            == b"updated"
        )
