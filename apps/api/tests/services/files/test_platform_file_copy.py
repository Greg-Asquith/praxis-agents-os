# apps/api/tests/services/files/test_platform_file_copy.py

"""Independent platform File copies, retry recovery, and editor authority."""

import asyncio
import hashlib
import importlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text

from core.database import maintenance_async_db_session, set_session_tenant_context
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.audit_event import AuditEvent
from models.files import File, FileRevision, FileUpload
from services.files.copy_file import copy_file
from services.files.domain import FileCopyRequest
from services.jobs.handlers.sweep_deleted_files import _purge_expired_uploads
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_file, build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


async def _copy_context(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    content = b"shared image"
    async with maintenance_async_db_session() as db:
        actor, workspace = (
            build_user(email=f"file-copy-{uuid4().hex}@example.com"),
            build_workspace(slug=f"file-copy-{uuid4().hex}"),
        )
        membership = build_workspace_membership(workspace_id=workspace.id, user_id=actor.id)
        db.add_all([actor, workspace, membership])
        source = build_file(
            workspace=workspace,
            workspace_id=None,
            scope="platform",
            name="shared.png",
            content_type="image/png",
            extension=".png",
            category="image",
            size_bytes=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        db.add(source)
        await db.flush()
        revision = FileRevision(
            id=uuid4(),
            file_id=source.id,
            scope="platform",
            workspace_id=None,
            revision_number=1,
            revision_kind="create",
            content_type=source.content_type,
            extension=source.extension,
            size_bytes=source.size_bytes,
            content_hash=source.content_hash,
            object_key=f"platform/files/{source.id}/{uuid4()}.png",
            created_by_system=True,
            is_published=True,
        )
        db.add(revision)
        await db.flush()
        source.current_revision_id = revision.id
        source.published_revision_id = revision.id
        source.is_published = True
        source.revision_count = 1
    provider = get_storage_provider()
    await provider.put_object(
        make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
        content,
        content_type="image/png",
    )
    try:
        yield (
            {
                "actor": actor,
                "workspace": workspace,
                "membership": membership,
                "file_id": source.id,
                "payload": FileCopyRequest(revision_id=revision.id, request_id=uuid4()),
            },
            content,
        )
    finally:
        reset_storage_provider_cache()


@pytest.fixture
async def copy_context(db_session_factory, monkeypatch, tmp_path):
    async for context in _copy_context(monkeypatch, tmp_path):
        yield context


@pytest.fixture
async def committed_copy_context(committed_db_session_factory, monkeypatch, tmp_path):
    async for context in _copy_context(monkeypatch, tmp_path):
        yield context


async def _tenant(db_session_factory, context):
    db = db_session_factory()
    await set_session_tenant_context(
        db, workspace_id=context["workspace"].id, user_id=context["actor"].id
    )
    return db


async def test_platform_copy_is_independent_and_retry_records_one_audit(
    db_session_factory, copy_context
):
    context, content = copy_context
    async with await _tenant(db_session_factory, context) as db:
        first = await copy_file(db, request=build_test_request(), **context)
        second = await copy_file(db, request=build_test_request(), **context)
        assert first.id == second.id != context["file_id"]
        assert first.scope == "workspace"
        assert first.workspace_id == context["workspace"].id
        revisions = list(
            (await db.scalars(select(FileRevision).where(FileRevision.file_id == first.id))).all()
        )
        assert len(revisions) == 1
        assert revisions[0].restored_from_revision_id is None
        assert revisions[0].created_by_user_id == context["actor"].id
        assert revisions[0].object_key.startswith(f"workspaces/{first.workspace_id}/files/")
        assert (
            await get_storage_provider().get_object(
                make_storage_object_ref(StorageBucket.PRIVATE, revisions[0].object_key)
            )
            == content
        )
        events = list(
            (
                await db.scalars(select(AuditEvent).where(AuditEvent.resource_id == str(first.id)))
            ).all()
        )
        assert len(events) == 1
        assert events[0].details["source_platform_file_id"] == str(context["file_id"])


async def test_platform_copy_audit_failure_keeps_retry_reservation(
    db_session_factory, copy_context, monkeypatch
):
    context, _ = copy_context
    module = importlib.import_module("services.files.copy_file")
    original = module.record_operation_audit_event
    monkeypatch.setattr(
        module,
        "record_operation_audit_event",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    async with await _tenant(db_session_factory, context) as db:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            await copy_file(db, request=build_test_request(), **context)
        await db.rollback()
        reservation = await db.scalar(
            select(FileUpload).where(FileUpload.workspace_id == context["workspace"].id)
        )
        assert reservation is not None and reservation.consumed_at is None
        assert await db.scalar(select(File).where(File.id == reservation.file_id)) is None
        assert (
            await get_storage_provider().stat_object(
                make_storage_object_ref(StorageBucket.PRIVATE, reservation.object_key)
            )
            is not None
        )
        monkeypatch.setattr(module, "record_operation_audit_event", original)
        recovered = await copy_file(db, request=build_test_request(), **context)
        assert recovered.id == reservation.file_id


@pytest.mark.parametrize("removed", [False, True])
async def test_platform_copy_rechecks_live_editor(db_session_factory, copy_context, removed):
    context, _ = copy_context
    async with maintenance_async_db_session() as db:
        membership = await db.get(type(context["membership"]), context["membership"].id)
        membership.role = "read_only"
        membership.deleted = removed
    async with await _tenant(db_session_factory, context) as db:
        with pytest.raises(AuthorizationError):
            await copy_file(db, request=build_test_request(), **context)
        assert (
            await db.scalar(
                select(FileUpload).where(FileUpload.workspace_id == context["workspace"].id)
            )
            is None
        )


async def test_platform_copy_rejects_withdrawn_and_other_parent_revision(
    db_session_factory, copy_context
):
    context, _ = copy_context
    async with await _tenant(db_session_factory, context) as db:
        with pytest.raises(NotFoundError):
            await copy_file(
                db,
                request=build_test_request(),
                **{**context, "payload": FileCopyRequest(revision_id=uuid4(), request_id=uuid4())},
            )
    async with maintenance_async_db_session() as db:
        source = await db.get(File, context["file_id"])
        source.is_published = False
    async with await _tenant(db_session_factory, context) as db:
        with pytest.raises(NotFoundError):
            await copy_file(db, request=build_test_request(), **context)


async def test_platform_copy_expired_failure_cleans_destination_and_stage(
    db_session_factory, copy_context, monkeypatch
):
    context, content = copy_context
    module = importlib.import_module("services.files.copy_file")
    monkeypatch.setattr(
        module,
        "record_operation_audit_event",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    async with await _tenant(db_session_factory, context) as db:
        with pytest.raises(RuntimeError):
            await copy_file(db, request=build_test_request(), **context)
        await db.rollback()
    async with maintenance_async_db_session() as db:
        reservation = await db.scalar(
            select(FileUpload).where(FileUpload.workspace_id == context["workspace"].id)
        )
        reservation.expires_at = datetime.now(UTC) - timedelta(hours=1)
        destination = make_storage_object_ref(StorageBucket.PRIVATE, reservation.object_key)
        stage = make_storage_object_ref(
            StorageBucket.PRIVATE,
            f"workspaces/{context['workspace'].id}/copy-staging/{hashlib.sha256(destination.uri.encode()).hexdigest()}",
        )
        await get_storage_provider().put_object(stage, content, content_type="image/png")
        await db.flush()
        await _purge_expired_uploads(db, now=datetime.now(UTC))
        assert await get_storage_provider().stat_object(destination) is None
        assert await get_storage_provider().stat_object(stage) is None
        assert await db.scalar(select(FileUpload).where(FileUpload.id == reservation.id)) is None


async def test_platform_copy_cleanup_failure_retains_reservation(
    db_session_factory, copy_context, monkeypatch
):
    context, _ = copy_context
    module = importlib.import_module("services.files.copy_file")
    monkeypatch.setattr(
        module,
        "record_operation_audit_event",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    async with await _tenant(db_session_factory, context) as db:
        with pytest.raises(RuntimeError):
            await copy_file(db, request=build_test_request(), **context)
    async with maintenance_async_db_session() as db:
        reservation = await db.scalar(
            select(FileUpload).where(FileUpload.workspace_id == context["workspace"].id)
        )
        reservation.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await db.flush()
        monkeypatch.setattr(
            get_storage_provider(),
            "delete_object",
            AsyncMock(side_effect=RuntimeError("storage unavailable")),
        )
        await _purge_expired_uploads(db, now=datetime.now(UTC))
        assert (
            await db.scalar(select(FileUpload).where(FileUpload.id == reservation.id))
            is reservation
        )


async def test_platform_copy_holds_source_lock_until_destination_audit_commits(
    committed_db_session_factory, committed_copy_context, monkeypatch
):
    context, _ = committed_copy_context
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", context["actor"].email)
    provider = get_storage_provider()
    promote = provider.promote_object
    copying = asyncio.Event()
    finish_copy = asyncio.Event()
    withdrawal_started = asyncio.Event()
    withdrawal_pid = None
    withdrawal = importlib.import_module("services.files.platform.withdraw_file")
    get_platform_file = withdrawal.get_platform_file
    observed_committed_copy = False

    async def paused_promote(*args, **kwargs):
        copying.set()
        await finish_copy.wait()
        return await promote(*args, **kwargs)

    async def observe_withdrawal(db, **kwargs):
        nonlocal withdrawal_pid, observed_committed_copy
        withdrawal_pid = await db.scalar(text("SELECT pg_backend_pid()"))
        withdrawal_started.set()
        source = await get_platform_file(db, **kwargs)
        destination = await db.scalar(
            select(File).where(File.workspace_id == context["workspace"].id)
        )
        assert destination is not None
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.resource_id == str(destination.id))
        )
        assert event is not None and event.details["source_platform_file_id"] == str(source.id)
        observed_committed_copy = True
        return source

    monkeypatch.setattr(provider, "promote_object", paused_promote)
    monkeypatch.setattr(withdrawal, "get_platform_file", observe_withdrawal)

    async def make_copy():
        async with await _tenant(committed_db_session_factory, context) as db:
            return await copy_file(db, request=build_test_request(), **context)

    async def withdraw():
        async with await _tenant(committed_db_session_factory, context) as db:
            return await withdrawal.withdraw_file(
                db, request=build_test_request(), actor=context["actor"], file_id=context["file_id"]
            )

    copy_task = asyncio.create_task(make_copy())
    withdrawal_task = None
    try:
        async with asyncio.timeout(10):
            await copying.wait()
            withdrawal_task = asyncio.create_task(withdraw())
            await withdrawal_started.wait()
            async with maintenance_async_db_session() as observer:
                # The database lock wait is external state, not an in-process event.
                while not await observer.scalar(  # noqa: ASYNC110
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                    {"pid": withdrawal_pid},
                ):
                    await asyncio.sleep(0.01)
            assert not withdrawal_task.done()
            finish_copy.set()
            copied, withdrawn = await asyncio.gather(copy_task, withdrawal_task)
        assert observed_committed_copy
        assert copied.scope == "workspace"
        assert withdrawn.is_published is False
    finally:
        finish_copy.set()
        tasks = [task for task in (copy_task, withdrawal_task) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with maintenance_async_db_session() as db:
            source = await db.get(File, context["file_id"])
            source.is_published = False
            source.current_revision_id = None
            source.published_revision_id = None
            await db.flush()
            await db.execute(delete(FileRevision).where(FileRevision.file_id == source.id))
            await db.delete(source)


@pytest.mark.parametrize("role, expected_status", [("member", 200), ("read_only", 403)])
async def test_platform_copy_http_editor_authority(
    db_async_client, copy_context, role, expected_status
):
    from core.auth.sessions import session_manager
    from tests.support.auth import bearer_headers

    context, _ = copy_context
    async with maintenance_async_db_session() as db:
        actor = await db.get(type(context["actor"]), context["actor"].id)
        actor.default_workspace_id = context["workspace"].id
        membership = await db.get(type(context["membership"]), context["membership"].id)
        membership.role = role
        session = await session_manager.create_session(db, str(actor.id))
    response = await db_async_client.post(
        f"/api/v1/files/{context['file_id']}/copy",
        headers=bearer_headers(session["session_token"]),
        json=context["payload"].model_dump(mode="json"),
    )
    assert response.status_code == expected_status, response.text
    if expected_status == 200:
        assert response.json()["scope"] == "workspace"
        assert response.json()["id"] != str(context["file_id"])
