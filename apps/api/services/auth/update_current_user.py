# apps/api/services/auth/update_current_user.py

"""Update the authenticated user's profile."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events import AuditAction, record_user_audit_event
from services.auth.schemas import AuthUser, CurrentUserUpdateRequest
from services.auth.utils import build_auth_user


async def update_current_user(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    payload: CurrentUserUpdateRequest,
) -> AuthUser:
    changed_fields: list[str] = []
    if "display_name" in payload.model_fields_set and payload.display_name != user.display_name:
        user.display_name = payload.display_name
        changed_fields.append("display_name")
    if "avatar_url" in payload.model_fields_set and payload.avatar_url != user.avatar_url:
        user.avatar_url = payload.avatar_url
        changed_fields.append("avatar_url")

    if changed_fields:
        await db.flush()
        await record_user_audit_event(
            db,
            action=AuditAction.UPDATE,
            user=user,
            actor=user,
            details={"fields": changed_fields},
            request=request,
        )
    return await build_auth_user(db, user)
