# apps/api/tests/services/files/test_platform_file_editing.py

"""Platform metadata and restore authority, isolation, and transaction guarantees."""

import importlib
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.audit_event import AuditEvent
from models.files import File, FileRevision
from models.workspace import WorkspaceRole
from services.files.domain import FileRestoreRequest, PlatformFileUpdateRequest
from services.files.platform.restore_file_revision import restore_file_revision
from services.files.platform.update_file import update_file
from tests.factories import build_file, build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request
from utils.content import ContentScope

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def editing_context(db_session_factory, monkeypatch):
    email = f"platform-editor-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", email)
    async with maintenance_async_db_session() as db:
        actor, workspace = build_user(email=email), build_workspace()
        db.add_all([actor, workspace])
        await db.flush()
        db.add(
            build_workspace_membership(
                workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.READ_ONLY
            )
        )
        file = build_file(
            workspace=workspace,
            scope=ContentScope.PLATFORM,
            workspace_id=None,
            name="policy.txt",
            extension=".txt",
            content_type="text/plain",
            category="editable_text",
        )
        db.add(file)
        await db.flush()
        revisions = []
        for number in (1, 2):
            revision = FileRevision(
                id=uuid4(),
                file_id=file.id,
                scope=ContentScope.PLATFORM,
                workspace_id=None,
                revision_number=number,
                revision_kind="create" if number == 1 else "replace",
                content_type="text/plain",
                extension=".txt",
                size_bytes=number,
                content_hash=str(number) * 64,
                object_key=f"platform/files/{file.id}/{uuid4()}.txt",
                created_by_user_id=actor.id,
                is_published=number == 1,
            )
            db.add(revision)
            revisions.append(revision)
        await db.flush()
        file.current_revision_id = revisions[1].id
        file.revision_count = 2
        file.published_revision_id = revisions[0].id
        file.is_published = True
    return actor, file, revisions


def _payload(file, revisions):
    return FileRestoreRequest(
        revision_id=revisions[0].id, expected_current_revision_id=file.current_revision_id
    )


@pytest.mark.parametrize("operation", [update_file, restore_file_revision])
async def test_platform_edit_denies_non_admin_before_maintenance(monkeypatch, operation):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    module = importlib.import_module("services.files.platform.utils")
    maintenance = Mock(side_effect=AssertionError("maintenance must remain closed"))
    monkeypatch.setattr(module, "maintenance_async_db_session", maintenance)
    db = AsyncMock(spec=AsyncSession)
    payload = (
        PlatformFileUpdateRequest(name="renamed.txt")
        if operation == update_file
        else (FileRestoreRequest(revision_id=uuid4(), expected_current_revision_id=uuid4()))
    )
    with pytest.raises(AuthorizationError):
        await operation(
            db, request=build_test_request(), actor=build_user(), file_id=uuid4(), payload=payload
        )
    maintenance.assert_not_called()
    db.commit.assert_not_awaited()


async def test_platform_metadata_edit_preserves_revision_and_audits_changed_fields(
    db_session, editing_context
):
    actor, file, revisions = editing_context
    result = await update_file(
        db_session,
        request=build_test_request(),
        actor=actor,
        file_id=file.id,
        payload=PlatformFileUpdateRequest(name="renamed.txt", description="Shared policy"),
    )
    assert result.name == "renamed.txt"
    assert result.description == "Shared policy"
    assert result.current_revision_id == revisions[1].id
    assert result.can_manage_platform is True
    async with maintenance_async_db_session() as db:
        stored = await db.get(File, file.id)
        assert stored.published_revision_id == revisions[0].id
        event = await db.scalar(select(AuditEvent).where(AuditEvent.resource_id == str(file.id)))
        assert event.workspace_id is None
        assert event.details["changed_fields"] == ["name", "description"]


async def test_platform_metadata_rejects_extension_change(db_session, editing_context):
    actor, file, _ = editing_context
    with pytest.raises(AppValidationError, match="extension"):
        await update_file(
            db_session,
            request=build_test_request(),
            actor=actor,
            file_id=file.id,
            payload=PlatformFileUpdateRequest(name="policy.pdf"),
        )


async def test_platform_restore_keeps_published_pointer_and_reuses_immutable_source(
    db_session, editing_context
):
    actor, file, revisions = editing_context
    result = await restore_file_revision(
        db_session,
        request=build_test_request(),
        actor=actor,
        file_id=file.id,
        payload=_payload(file, revisions),
    )
    assert result.revision_count == 3
    assert result.current_revision_id not in {revision.id for revision in revisions}
    async with maintenance_async_db_session() as db:
        restored = await db.get(FileRevision, result.current_revision_id)
        stored = await db.get(File, file.id)
        assert restored.object_key == revisions[0].object_key
        assert restored.restored_from_revision_id == revisions[0].id
        assert restored.is_published is False
        assert restored.scope == ContentScope.PLATFORM
        assert restored.workspace_id is None
        assert stored.published_revision_id == revisions[0].id
        assert stored.is_published is True
        event = await db.scalar(select(AuditEvent).where(AuditEvent.resource_id == str(file.id)))
        assert event.details["operation"] == "restore"
        assert event.details["revision_id"] == str(restored.id)
        assert event.workspace_id is None


@pytest.mark.parametrize("case", ["stale", "current", "missing"])
async def test_platform_restore_rejects_invalid_selection(db_session, editing_context, case):
    actor, file, revisions = editing_context
    payload = _payload(file, revisions)
    if case == "stale":
        payload.expected_current_revision_id = uuid4()
    else:
        payload.revision_id = file.current_revision_id if case == "current" else uuid4()
    error = {"stale": ConflictError, "current": AppValidationError, "missing": NotFoundError}[case]
    with pytest.raises(error):
        await restore_file_revision(
            db_session, request=build_test_request(), actor=actor, file_id=file.id, payload=payload
        )


@pytest.mark.parametrize("operation", [update_file, restore_file_revision])
async def test_platform_edit_audit_failure_rolls_back(
    db_session, editing_context, monkeypatch, operation
):
    actor, file, revisions = editing_context
    module = importlib.import_module("services.files.platform.utils")
    monkeypatch.setattr(
        module,
        "record_platform_content_audit_event",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    payload = (
        PlatformFileUpdateRequest(name="renamed.txt")
        if operation == update_file
        else _payload(file, revisions)
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await operation(
            db_session, request=build_test_request(), actor=actor, file_id=file.id, payload=payload
        )
    async with maintenance_async_db_session() as db:
        stored = await db.get(File, file.id)
        assert stored.name == file.name
        assert stored.current_revision_id == revisions[1].id
        assert stored.published_revision_id == revisions[0].id
        assert (
            await db.scalar(
                select(func.count())
                .select_from(FileRevision)
                .where(FileRevision.file_id == file.id)
            )
            == 2
        )


async def test_platform_restore_rejects_revision_from_another_platform_parent(
    db_session, editing_context
):
    actor, _, revisions = editing_context
    async with maintenance_async_db_session() as db:
        workspace = build_workspace(slug=f"other-{uuid4().hex}")
        db.add(workspace)
        await db.flush()
        other = build_file(workspace=workspace, scope=ContentScope.PLATFORM, workspace_id=None)
        db.add(other)
        await db.flush()
        revision = FileRevision(
            id=uuid4(),
            file_id=other.id,
            scope=ContentScope.PLATFORM,
            workspace_id=None,
            revision_number=1,
            revision_kind="create",
            content_type=other.content_type,
            extension=other.extension,
            size_bytes=other.size_bytes,
            content_hash=other.content_hash,
            object_key=f"platform/files/{other.id}/{uuid4()}.pdf",
            created_by_user_id=actor.id,
        )
        db.add(revision)
        await db.flush()
        other.current_revision_id = revision.id
        other.revision_count = 1
    with pytest.raises(NotFoundError):
        await restore_file_revision(
            db_session,
            request=build_test_request(),
            actor=actor,
            file_id=other.id,
            payload=FileRestoreRequest(
                revision_id=revisions[0].id,
                expected_current_revision_id=revision.id,
            ),
        )


async def test_platform_restore_after_withdrawal_clears_pointer_and_keeps_publication_history(
    db_session, editing_context
):
    actor, file, revisions = editing_context
    async with maintenance_async_db_session() as db:
        stored = await db.get(File, file.id)
        stored.is_published = False
    result = await restore_file_revision(
        db_session,
        request=build_test_request(),
        actor=actor,
        file_id=file.id,
        payload=_payload(file, revisions),
    )
    assert result.is_published is False
    assert result.revision_count == 3
    async with maintenance_async_db_session() as db:
        stored = await db.get(File, file.id)
        restored = await db.get(FileRevision, result.current_revision_id)
        published = await db.get(FileRevision, revisions[0].id)
        assert stored.published_revision_id is None
        assert restored.is_published is False
        assert restored.restored_from_revision_id == published.id
        assert restored.object_key == published.object_key
        assert published.is_published is True
