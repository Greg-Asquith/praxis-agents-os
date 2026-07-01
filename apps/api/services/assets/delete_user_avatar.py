# apps/api/services/assets/delete_user_avatar.py

"""Delete the authenticated user's managed avatar."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.utils import best_effort_delete_public_object
from services.audit_events import AuditAction, record_user_audit_event
from services.auth.schemas import AuthUser
from services.auth.utils import build_auth_user
from services.storage.factory import get_storage_provider


async def delete_user_avatar(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
) -> AuthUser:
    previous_object_key = actor.avatar_object_key
    provider = get_storage_provider()

    if actor.avatar_url is not None or actor.avatar_object_key is not None:
        actor.avatar_url = None
        actor.avatar_object_key = None
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

    if previous_object_key:
        await best_effort_delete_public_object(previous_object_key, provider=provider)

    return await build_auth_user(db, actor)
