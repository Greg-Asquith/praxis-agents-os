# apps/api/services/assets/confirm_user_avatar_upload.py

"""Confirm an uploaded avatar and attach it to the authenticated user."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.domain import AssetConfirmRequest, AssetKind
from services.assets.tokens import token_ref, verify_asset_upload_token
from services.assets.utils import (
    allowed_avatar_content_types,
    best_effort_delete_public_object,
    resolve_public_url,
    validate_stored_object,
)
from services.audit_events import AuditAction, record_user_audit_event
from services.auth.schemas import AuthUser
from services.auth.utils import build_auth_user
from services.storage.factory import get_storage_provider


async def confirm_user_avatar_upload(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    payload: AssetConfirmRequest,
) -> AuthUser:
    token_payload = verify_asset_upload_token(
        payload.upload_token,
        expected_kind=AssetKind.USER_AVATAR,
        actor_user_id=actor.id,
        target_user_id=actor.id,
    )
    ref = token_ref(token_payload)
    provider = get_storage_provider()

    try:
        stored = validate_stored_object(
            await provider.stat_object(ref),
            expected_content_type=token_payload.content_type,
            allowed_content_types=allowed_avatar_content_types(),
            max_size_bytes=token_payload.max_size_bytes,
            asset_label="avatar",
        )
        public_url = resolve_public_url(stored, provider=provider, asset_label="avatar")
    except Exception:
        await best_effort_delete_public_object(ref.key, provider=provider)
        raise

    previous_object_key = actor.avatar_object_key
    actor.avatar_object_key = ref.key
    actor.avatar_url = public_url
    await db.flush()
    await record_user_audit_event(
        db,
        action=AuditAction.UPDATE,
        user=actor,
        actor=actor,
        details={
            "fields": ["avatar_url", "avatar_object_key"],
            "storage_provider": provider.provider_key,
        },
        request=request,
    )

    if previous_object_key and previous_object_key != ref.key:
        await best_effort_delete_public_object(previous_object_key, provider=provider)

    return await build_auth_user(db, actor)
