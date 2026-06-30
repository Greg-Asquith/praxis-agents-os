# apps/api/services/users/set_user_password.py

"""Set a user's password through super-admin user management."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.user import User
from services.audit_events import AuditAction, record_user_audit_event
from services.users.schemas import UserPasswordSetRequest, UserRead
from services.users.utils import get_user_or_raise
from utils.validation import validate_password_strength


async def set_user_password(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    user_id: UUID,
    payload: UserPasswordSetRequest,
) -> UserRead:
    validate_password_strength(payload.password)
    user = await get_user_or_raise(db, user_id=user_id)
    user.set_password(payload.password)
    revoked_sessions = await session_manager.revoke_user_sessions(db, user_id=str(user.id))
    await db.flush()
    await record_user_audit_event(
        db,
        action=AuditAction.UPDATE,
        user=user,
        actor=actor,
        request=request,
        details={"field": "password", "revoked_sessions": revoked_sessions},
    )
    await db.refresh(user)
    return UserRead.from_user(user)
