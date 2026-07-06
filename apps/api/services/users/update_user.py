# apps/api/services/users/update_user.py

"""Update a user through super-admin user management."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.exceptions.general import AppValidationError
from models.user import User
from services.audit_events import AuditAction, record_user_audit_event
from services.users.schemas import UserRead, UserUpdateRequest
from services.users.utils import get_user_or_raise


async def update_user(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    user_id: UUID,
    payload: UserUpdateRequest,
) -> UserRead:
    user = await get_user_or_raise(db, user_id=user_id)
    changed_fields: list[str] = []
    revoked_sessions = 0

    if "display_name" in payload.model_fields_set and payload.display_name != user.display_name:
        user.display_name = payload.display_name
        changed_fields.append("display_name")
    if "is_active" in payload.model_fields_set:
        if payload.is_active is None:
            raise AppValidationError("is_active cannot be null", field="is_active")
        if payload.is_active != user.is_active:
            user.is_active = payload.is_active
            changed_fields.append("is_active")
            if payload.is_active is False:
                revoked_sessions = await session_manager.revoke_user_sessions(
                    db, user_id=str(user.id)
                )

    if changed_fields:
        await db.flush()
        await record_user_audit_event(
            db,
            action=AuditAction.UPDATE,
            user=user,
            actor=actor,
            request=request,
            details={"fields": changed_fields, "revoked_sessions": revoked_sessions},
        )
        await db.refresh(user)

    return UserRead.from_user(user)
