# apps/api/tests/services/assets/test_workspace_icon_assets.py

"""Service tests for workspace icon asset uploads."""

from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.audit_event import AuditEvent
from models.workspace import WorkspaceRole
from services.assets import (
    confirm_workspace_icon_upload,
    create_workspace_icon_upload,
)
from services.assets.domain import AssetConfirmRequest, AssetUploadRequest
from services.audit_events import AuditAction, AuditResourceType
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_user, build_workspace, build_workspace_membership
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


async def test_confirm_workspace_icon_upload_sets_url_key_audits_and_deletes_previous_object(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor = build_user(email="workspace-admin@example.com")
    workspace = build_workspace(slug="asset-workspace")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.ADMIN,
    )
    provider = get_storage_provider()
    previous_ref = make_storage_object_ref(
        StorageBucket.PUBLIC,
        f"workspaces/{workspace.id}/icon/previous.webp",
    )
    previous = await provider.put_object(previous_ref, b"old", content_type="image/webp")
    workspace.icon_object_key = previous_ref.key
    workspace.icon_url = previous.public_url
    db_session.add_all([actor, workspace, membership])
    await db_session.flush()

    grant = await create_workspace_icon_upload(
        db_session,
        actor=actor,
        workspace_id=workspace.id,
        payload=AssetUploadRequest(
            filename="icon.webp",
            content_type="image/webp",
            size_bytes=8,
        ),
    )
    await provider.put_object(grant.upload.ref, b"new-webp", content_type="image/webp")

    result = await confirm_workspace_icon_upload(
        db_session,
        request=build_test_request(path=f"/api/v1/workspaces/{workspace.id}/icon/confirm"),
        actor=actor,
        workspace_id=workspace.id,
        payload=AssetConfirmRequest(upload_token=grant.upload_token),
    )

    assert workspace.icon_object_key == grant.upload.ref.key
    assert result.icon_url is not None
    assert result.icon_url.endswith(grant.upload.ref.key)
    assert await provider.stat_object(previous_ref) is None

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.UPDATE.value,
            AuditEvent.resource_type == AuditResourceType.WORKSPACE.value,
            AuditEvent.resource_id == str(workspace.id),
        )
    )
    assert audit_event is not None
    assert audit_event.details == {
        "fields": ["icon_url", "icon_object_key"],
        "storage_provider": provider.provider_key,
    }


async def test_workspace_icon_upload_rejects_svg_even_if_icon_settings_include_svg(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = build_user(email="workspace-owner@example.com")
    workspace = build_workspace(slug="svg-rejected")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add_all([actor, workspace, membership])
    await db_session.flush()
    monkeypatch.setattr(settings, "ALLOWED_ICON_TYPES", "image/svg+xml,image/png")

    with pytest.raises(AppValidationError, match="Unsupported workspace icon file type"):
        await create_workspace_icon_upload(
            db_session,
            actor=actor,
            workspace_id=workspace.id,
            payload=AssetUploadRequest(
                filename="icon.svg",
                content_type="image/svg+xml",
                size_bytes=128,
            ),
        )
