"""Platform audit authority, global visibility, and rollback contracts."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    SESSION_MAINTENANCE_KEY,
    maintenance_async_db_session,
    set_session_tenant_context,
)
from core.exceptions.auth import AuthorizationError
from core.settings import settings
from models.audit_event import AuditEvent
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.platform_content_events import (
    PlatformContentAuditDetails,
    PlatformContentSource,
    record_platform_content_audit_event,
)
from tests.factories import build_user, build_workspace


@pytest.mark.parametrize(
    "resource_type",
    [AuditResourceType.FILE, AuditResourceType.KB_DOCUMENT, AuditResourceType.ARTIFACT],
)
@pytest.mark.parametrize(
    "operation", ["create", "update", "replace", "restore", "publish", "withdraw", "delete"]
)
async def test_audit_shape(monkeypatch, resource_type, operation):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    actor = build_user(email="admin@example.com")
    db = AsyncMock(spec=AsyncSession)
    db.info = {SESSION_MAINTENANCE_KEY: True}
    resource_id, revision_id = uuid4(), uuid4()
    source = PlatformContentSource(workspace_id=uuid4(), resource_id=uuid4(), revision_id=uuid4())
    event = await record_platform_content_audit_event(
        db,
        request=Request({"type": "http", "headers": []}),
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        details=PlatformContentAuditDetails(
            operation=operation, revision_id=revision_id, source=source
        ),
    )
    assert event.workspace_id is None
    assert event.actor_user_id == event.requested_by_user_id == actor.id
    assert event.resource_id == str(resource_id)
    assert event.resource_type == resource_type
    assert event.action == {"create": AuditAction.CREATE, "delete": AuditAction.DELETE}.get(
        operation, AuditAction.UPDATE
    )
    assert event.details == {
        "scope": "platform",
        "operation": operation,
        "revision_id": str(revision_id),
        "changed_fields": [],
        "source": source.model_dump(mode="json"),
    }
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("admin,maintenance", [(False, False), (False, True), (True, False)])
async def test_audit_denies_before_writing(monkeypatch, admin, maintenance):
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    actor = build_user(email="admin@example.com" if admin else "member@example.com")
    db = AsyncMock(spec=AsyncSession)
    db.info = {SESSION_MAINTENANCE_KEY: maintenance}
    with pytest.raises(AuthorizationError):
        await record_platform_content_audit_event(
            db,
            request=Request({"type": "http", "headers": []}),
            actor=actor,
            resource_type=AuditResourceType.FILE,
            resource_id=uuid4(),
            details=PlatformContentAuditDetails(operation="publish"),
        )
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "fields",
    [
        {"scope": "workspace"},
        {"content": "private"},
        {"download_url": "secret"},
        {"credentials": "secret"},
    ],
)
def test_audit_rejects_unrestricted_details(fields):
    with pytest.raises(ValidationError):
        PlatformContentAuditDetails(operation="publish", **fields)


async def test_global_audit_is_hidden_from_tenants_and_failure_rolls_back(
    db_session_factory, monkeypatch
):
    from models.kb import KBDocument
    from services.audit_events import platform_content_events as module
    from tests.factories import build_kb_document

    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    async with maintenance_async_db_session() as db:
        actor, workspace = build_user(email="admin@example.com"), build_workspace()
        db.add_all([actor, workspace])
        await db.flush()
        document = build_kb_document(
            workspace=workspace, scope="platform", workspace_id=None, is_private=False
        )
        db.add(document)
        await db.flush()
        document_id = document.id
        event = await record_platform_content_audit_event(
            db,
            request=Request({"type": "http", "headers": []}),
            actor=actor,
            resource_type=AuditResourceType.KB_DOCUMENT,
            resource_id=document.id,
            details=PlatformContentAuditDetails(operation="create"),
        )
        event_id = event.id
    async with db_session_factory() as tenant:
        await set_session_tenant_context(tenant, workspace_id=workspace.id, user_id=actor.id)
        assert await tenant.scalar(select(AuditEvent).where(AuditEvent.id == event_id)) is None

    monkeypatch.setattr(
        module,
        "record_operation_audit_event",
        AsyncMock(side_effect=RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        async with maintenance_async_db_session() as db:
            document = await db.get(KBDocument, document_id, with_for_update=True)
            document.is_published = True
            await db.flush()
            await record_platform_content_audit_event(
                db,
                request=Request({"type": "http", "headers": []}),
                actor=actor,
                resource_type=AuditResourceType.KB_DOCUMENT,
                resource_id=document.id,
                details=PlatformContentAuditDetails(operation="publish"),
            )
    async with maintenance_async_db_session() as db:
        assert (await db.get(KBDocument, document_id)).is_published is False
        assert await db.get(AuditEvent, event_id) is not None


@pytest.mark.parametrize("role", ["owner", "admin", "member", "read_only"])
async def test_editor_revision_publication_audit(monkeypatch, role):
    from models.workspace import WorkspaceRole
    from tests.factories import build_artifact, build_workspace_membership

    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "")
    actor, workspace = build_user(), build_workspace()
    membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole(role)
    )
    artifact = build_artifact(
        workspace=workspace, workspace_id=None, scope="platform", is_published=True
    )
    db = AsyncMock(spec=AsyncSession)
    db.info = {SESSION_MAINTENANCE_KEY: True}
    kwargs = {
        "request": Request({"type": "http", "headers": []}),
        "actor": actor,
        "resource_type": AuditResourceType.ARTIFACT,
        "resource_id": artifact.id,
        "details": PlatformContentAuditDetails(operation="publish_revision", revision_id=uuid4()),
        "artifact": artifact,
        "membership": membership,
    }
    if role == "read_only":
        with pytest.raises(AuthorizationError):
            await record_platform_content_audit_event(db, **kwargs)
        db.flush.assert_not_awaited()
    else:
        event = await record_platform_content_audit_event(db, **kwargs)
        assert event.workspace_id is None
        assert event.actor_user_id == actor.id
        assert event.details["operation"] == "publish_revision"


@pytest.mark.parametrize(
    "invalid",
    ["file", "knowledge", "wrong_id", "missing_revision", "missing_membership", "withdrawn"],
)
async def test_editor_audit_exception_is_limited_to_published_artifact_versions(
    monkeypatch, invalid
):
    from tests.factories import build_artifact, build_workspace_membership

    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "")
    actor, workspace = build_user(), build_workspace()
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=actor.id)
    artifact = build_artifact(
        workspace=workspace,
        workspace_id=None,
        scope="platform",
        is_published=invalid != "withdrawn",
    )
    db = AsyncMock(spec=AsyncSession)
    db.info = {SESSION_MAINTENANCE_KEY: True}
    with pytest.raises(AuthorizationError):
        await record_platform_content_audit_event(
            db,
            request=Request({"type": "http", "headers": []}),
            actor=actor,
            resource_type={
                "file": AuditResourceType.FILE,
                "knowledge": AuditResourceType.KB_DOCUMENT,
            }.get(invalid, AuditResourceType.ARTIFACT),
            resource_id=uuid4() if invalid == "wrong_id" else artifact.id,
            details=PlatformContentAuditDetails(
                operation="publish_revision",
                revision_id=None if invalid == "missing_revision" else uuid4(),
            ),
            artifact=artifact,
            membership=None if invalid == "missing_membership" else membership,
        )
    db.flush.assert_not_awaited()
