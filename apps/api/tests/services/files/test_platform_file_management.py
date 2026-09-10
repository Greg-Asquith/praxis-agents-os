# apps/api/tests/services/files/test_platform_file_management.py

"""Platform File publication, authenticated review, and transaction boundaries."""

import importlib
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import ConflictError, NotFoundError
from core.settings import settings
from models.audit_event import AuditEvent
from models.files import File, FileRevision
from models.workspace import WorkspaceRole
from services.files import confirm_file_upload, create_file_upload
from services.files.domain import FileConfirmRequest, FileUploadRequest, PlatformFilePublishRequest
from services.files.platform.delete_file import delete_file
from services.files.platform.get_file import get_file
from services.files.platform.get_file_content import get_file_content
from services.files.platform.get_file_preview import get_file_preview
from services.files.platform.list_file_revisions import list_file_revisions
from services.files.platform.list_files import list_files
from services.files.platform.publish_file import publish_file
from services.files.platform.withdraw_file import withdraw_file
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.errors import StoragePreconditionError
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request
from tests.support.storage import reset_storage_provider_cache
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def management_context(db_session_factory, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    email = f"platform-manager-{uuid4().hex}@example.com"
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


async def _draft(db, context, *, content=b"hello", file_id=None, image=False, pdf=False):
    content_type = "application/pdf" if pdf else "image/png" if image else "text/plain"
    result = await create_file_upload(
        db,
        **context,
        scope=ContentScope.PLATFORM,
        payload=FileUploadRequest(
            filename="shared.pdf" if pdf else "shared.png" if image else "shared.txt",
            content_type=content_type,
            size_bytes=len(content),
            file_id=file_id,
        ),
    )
    grant = result.grant
    assert grant is not None
    await get_storage_provider().put_object(grant.upload.ref, content, content_type=content_type)
    return await confirm_file_upload(
        db,
        **context,
        scope=ContentScope.PLATFORM,
        request=build_test_request(),
        payload=FileConfirmRequest(upload_token=grant.upload_token),
    )


async def _publish(db, actor, file):
    return await publish_file(
        db,
        actor=actor,
        request=build_test_request(),
        file_id=file.id,
        payload=PlatformFilePublishRequest(expected_current_revision_id=file.current_revision_id),
    )


OPERATIONS = [
    "get_file",
    "get_file_content",
    "get_file_preview",
    "list_files",
    "list_file_revisions",
    "publish_file",
    "withdraw_file",
    "delete_file",
]


async def _operation(name, db, actor):
    module = importlib.import_module(f"services.files.platform.{name}")
    kwargs = {"actor": actor}
    if name != "list_files":
        kwargs["file_id"] = uuid4()
    if name in {"publish_file", "withdraw_file", "delete_file"}:
        kwargs["request"] = build_test_request()
    if name == "publish_file":
        kwargs["payload"] = PlatformFilePublishRequest(expected_current_revision_id=uuid4())
    return await getattr(module, name)(db, **kwargs)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("failure", ["authority", "request_commit"])
async def test_platform_management_checks_authority_and_commit_before_maintenance(
    monkeypatch, operation, failure
):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    actor = build_user(
        email="member@example.com" if failure == "authority" else "admin@example.com"
    )
    db = AsyncMock(spec=AsyncSession)
    db.commit.side_effect = RuntimeError("request commit failed")
    module = importlib.import_module("services.files.platform.utils")
    maintenance = Mock(side_effect=AssertionError("maintenance must remain closed"))
    audit = AsyncMock()
    monkeypatch.setattr(module, "maintenance_async_db_session", maintenance)
    monkeypatch.setattr(module, "record_platform_content_audit_event", audit)
    expected = AuthorizationError if failure == "authority" else RuntimeError
    with pytest.raises(expected):
        await _operation(operation, db, actor)
    maintenance.assert_not_called()
    audit.assert_not_awaited()
    if failure == "authority":
        db.commit.assert_not_awaited()
    else:
        db.commit.assert_awaited_once_with()


async def test_platform_read_only_admin_publication_lifecycle(db_session, management_context):
    actor = management_context["actor"]
    first = await _draft(db_session, management_context)
    assert not first.is_published
    published = await _publish(db_session, actor, first)
    assert published.is_published
    second = await _draft(db_session, management_context, file_id=first.id, content=b"updated")
    async with maintenance_async_db_session() as db:
        file = await db.get(File, first.id)
        assert file.published_revision_id == first.current_revision_id
        assert not (await db.get(FileRevision, second.current_revision_id)).is_published
    await _publish(db_session, actor, second)
    withdrawn = await withdraw_file(
        db_session, actor=actor, request=build_test_request(), file_id=first.id
    )
    assert not withdrawn.is_published
    async with maintenance_async_db_session() as db:
        file = await db.get(File, first.id)
        assert file.published_revision_id == second.current_revision_id
        for revision_id in (first.current_revision_id, second.current_revision_id):
            assert (await db.get(FileRevision, revision_id)).is_published
        events = (
            await db.scalars(
                select(AuditEvent)
                .where(AuditEvent.resource_id == str(first.id))
                .order_by(AuditEvent.created_at)
            )
        ).all()
        assert [event.details["operation"] for event in events] == [
            "create",
            "publish",
            "replace",
            "publish",
            "withdraw",
        ]
        assert all(event.workspace_id is None for event in events)
    assert (await get_file_content(db_session, actor=actor, file_id=first.id)).content == "updated"
    await delete_file(db_session, actor=actor, request=build_test_request(), file_id=first.id)
    with pytest.raises(NotFoundError):
        await get_file(db_session, actor=actor, file_id=first.id)


@pytest.mark.parametrize("operation", ["publish", "withdraw", "delete"])
async def test_platform_lifecycle_audit_failure_rolls_back(
    db_session, management_context, monkeypatch, operation
):
    actor = management_context["actor"]
    draft = await _draft(db_session, management_context)
    if operation != "publish":
        await _publish(db_session, actor, draft)
    module = importlib.import_module("services.files.platform.utils")
    monkeypatch.setattr(
        module,
        "record_platform_content_audit_event",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        if operation == "publish":
            await _publish(db_session, actor, draft)
        else:
            function = withdraw_file if operation == "withdraw" else delete_file
            await function(db_session, actor=actor, request=build_test_request(), file_id=draft.id)
    async with maintenance_async_db_session() as db:
        file = await db.get(File, draft.id)
        revision = await db.get(FileRevision, draft.current_revision_id)
        assert not file.deleted
        assert file.is_published == (operation != "publish")
        assert revision.is_published == (operation != "publish")
        assert file.published_revision_id == (None if operation == "publish" else revision.id)
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(draft.id)))
        ).all()
        assert len(events) == (1 if operation == "publish" else 2)


async def test_platform_publish_rejects_stale_review(db_session, management_context):
    actor = management_context["actor"]
    first = await _draft(db_session, management_context)
    second = await _draft(db_session, management_context, file_id=first.id, content=b"updated")
    with pytest.raises(ConflictError):
        await _publish(db_session, actor, first)
    async with maintenance_async_db_session() as db:
        file = await db.get(File, first.id)
        assert file.current_revision_id == second.current_revision_id
        assert file.published_revision_id is None
        assert not file.is_published


@pytest.mark.parametrize("operation", [get_file_content, get_file_preview])
async def test_platform_review_rejects_revision_from_another_parent(
    db_session, management_context, operation
):
    first = await _draft(db_session, management_context)
    other = await _draft(db_session, management_context)
    with pytest.raises(NotFoundError):
        await operation(
            db_session,
            actor=management_context["actor"],
            file_id=first.id,
            revision_id=other.current_revision_id,
        )


@pytest.mark.parametrize("content", [b"wrong", b"too long"])
@pytest.mark.parametrize("operation", ["content", "preview", "publish"])
async def test_platform_review_and_publication_reject_changed_bytes(
    db_session, management_context, content, operation
):
    draft = await _draft(db_session, management_context, image=operation == "preview")
    async with maintenance_async_db_session() as db:
        revision = await db.get(FileRevision, draft.current_revision_id)
        ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key)
    await get_storage_provider().put_object(ref, content, content_type=draft.content_type)
    with pytest.raises(StoragePreconditionError):
        if operation == "publish":
            await _publish(db_session, management_context["actor"], draft)
        else:
            function = get_file_content if operation == "content" else get_file_preview
            await function(db_session, actor=management_context["actor"], file_id=draft.id)


async def test_platform_draft_review_returns_content_without_signed_capabilities(
    db_session, management_context, monkeypatch
):
    actor = management_context["actor"]
    text = await _draft(db_session, management_context)
    picture = await _draft(db_session, management_context, image=True)
    provider = get_storage_provider()
    signed = AsyncMock(side_effect=AssertionError("review must not issue a capability"))
    monkeypatch.setattr(provider, "create_signed_download", signed)
    assert (await get_file_content(db_session, actor=actor, file_id=text.id)).content == "hello"
    assert await get_file_preview(db_session, actor=actor, file_id=picture.id) == (
        b"hello",
        "image/png",
    )
    signed.assert_not_awaited()


async def test_platform_lists_exclude_workspace_and_deleted_files_and_page_revisions(
    db_session, management_context
):
    actor = management_context["actor"]
    first = await _draft(db_session, management_context)
    second = await _draft(db_session, management_context, file_id=first.id, content=b"updated")
    deleted = await _draft(db_session, management_context)
    await delete_file(db_session, actor=actor, request=build_test_request(), file_id=deleted.id)
    async with maintenance_async_db_session() as db:
        local = build_file(workspace=management_context["workspace"])
        db.add(local)
    result = await list_files(db_session, actor=actor)
    assert {file.id for file in result.files} == {first.id}
    assert result.total == 1
    history = await list_file_revisions(db_session, actor=actor, file_id=first.id, limit=1)
    assert history.total == 2
    assert [revision.id for revision in history.revisions] == [second.current_revision_id]
    older = await list_file_revisions(db_session, actor=actor, file_id=first.id, limit=1, offset=1)
    assert [revision.id for revision in older.revisions] == [first.current_revision_id]
    with pytest.raises(NotFoundError):
        await get_file(db_session, actor=actor, file_id=local.id)


async def test_platform_publication_changes_real_tenant_visibility(
    db_session, db_session_factory, management_context
):
    actor = management_context["actor"]
    first = await _draft(db_session, management_context)
    workspaces = (management_context["workspace"].id, uuid4())

    async def assert_visible(expected_revision_ids, published_revision_id):
        for workspace_id in workspaces:
            async with db_session_factory() as tenant:
                await set_session_tenant_context(tenant, workspace_id=workspace_id)
                file = await tenant.get(File, first.id)
                revisions = set(
                    await tenant.scalars(
                        select(FileRevision.id).where(FileRevision.file_id == first.id)
                    )
                )
                assert revisions == expected_revision_ids
                if published_revision_id is None:
                    assert file is None
                else:
                    assert file is not None
                    assert file.published_revision_id == published_revision_id

    await assert_visible(set(), None)
    await _publish(db_session, actor, first)
    await assert_visible({first.current_revision_id}, first.current_revision_id)
    second = await _draft(db_session, management_context, file_id=first.id, content=b"updated")
    await assert_visible({first.current_revision_id}, first.current_revision_id)
    await _publish(db_session, actor, second)
    await assert_visible(
        {first.current_revision_id, second.current_revision_id}, second.current_revision_id
    )
    await withdraw_file(db_session, actor=actor, request=build_test_request(), file_id=first.id)
    await assert_visible(set(), None)


async def test_withdrawn_file_replacement_processes_and_republishes(
    db_session, management_context, monkeypatch
):
    from models.jobs import Job
    from services.jobs.handlers import extract_platform_file_markdown as extraction

    monkeypatch.setattr(
        extraction, "convert_document_to_markdown", AsyncMock(return_value="Shared guidance")
    )
    actor = management_context["actor"]

    async def extract(file):
        async with maintenance_async_db_session() as db:
            job = await db.scalar(select(Job).where(Job.subject_id == file.current_revision_id))
        await extraction.extract_platform_file_markdown(db_session, job)

    first = await _draft(db_session, management_context, pdf=True)
    await extract(first)
    await _publish(db_session, actor, first)
    await withdraw_file(db_session, actor=actor, request=build_test_request(), file_id=first.id)
    replacement = await _draft(
        db_session, management_context, pdf=True, file_id=first.id, content=b"revised"
    )
    assert replacement.published_revision_id is None
    await extract(replacement)
    published = await _publish(db_session, actor, replacement)
    assert published.published_revision_id == replacement.current_revision_id
    async with maintenance_async_db_session() as db:
        assert (await db.get(FileRevision, first.current_revision_id)).is_published
        assert (await db.get(FileRevision, replacement.current_revision_id)).markdown_object_key
