# apps/api/tests/services/assets/test_user_avatar_assets.py

"""Service tests for current-user avatar asset uploads."""

from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.audit_event import AuditEvent
from services.assets import (
    confirm_user_avatar_upload,
    create_user_avatar_upload,
    delete_user_avatar,
)
from services.assets.domain import AssetConfirmRequest, AssetUploadRequest
from services.audit_events import AuditAction, AuditResourceType
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from tests.factories import build_user
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


async def test_confirm_user_avatar_upload_sets_url_key_audits_and_deletes_previous_object(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor = build_user(email="avatar-owner@example.com")
    provider = get_storage_provider()
    previous_ref = make_storage_object_ref(
        StorageBucket.PUBLIC,
        f"users/{actor.id}/avatar/previous.png",
    )
    previous = await provider.put_object(previous_ref, b"old", content_type="image/png")
    actor.avatar_object_key = previous_ref.key
    actor.avatar_url = previous.public_url
    db_session.add(actor)
    await db_session.flush()

    grant = await create_user_avatar_upload(
        actor=actor,
        payload=AssetUploadRequest(
            filename="avatar.png",
            content_type="image/png",
            size_bytes=7,
        ),
    )
    await provider.put_object(grant.upload.ref, b"new-png", content_type="image/png")

    result = await confirm_user_avatar_upload(
        db_session,
        request=build_test_request(path="/api/v1/auth/me/avatar/confirm"),
        actor=actor,
        payload=AssetConfirmRequest(upload_token=grant.upload_token),
    )

    assert actor.avatar_object_key == grant.upload.ref.key
    assert result.avatar_url is not None
    assert result.avatar_url.endswith(grant.upload.ref.key)
    assert await provider.stat_object(previous_ref) is None

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.UPDATE.value,
            AuditEvent.resource_type == AuditResourceType.USER.value,
            AuditEvent.resource_id == str(actor.id),
        )
    )
    assert audit_event is not None
    assert audit_event.details == {
        "fields": ["avatar_url", "avatar_object_key"],
        "storage_provider": provider.provider_key,
    }


async def test_delete_user_avatar_clears_external_oauth_url_without_requiring_object_key(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    actor = build_user(email="oauth-avatar@example.com")
    actor.avatar_url = "https://accounts.example/avatar.png"
    db_session.add(actor)
    await db_session.flush()

    result = await delete_user_avatar(
        db_session,
        request=build_test_request(path="/api/v1/auth/me/avatar", method="DELETE"),
        actor=actor,
    )

    assert actor.avatar_url is None
    assert actor.avatar_object_key is None
    assert result.avatar_url is None

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.UPDATE.value,
            AuditEvent.resource_type == AuditResourceType.USER.value,
            AuditEvent.resource_id == str(actor.id),
        )
    )
    assert audit_event is not None
    assert audit_event.details["fields"] == ["avatar_url", "avatar_object_key"]
