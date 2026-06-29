# apps/api/services/users/delete_user.py

"""Delete a user through super-admin user management."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.exceptions.general import AppValidationError
from models.user import User
from services.audit_events import AuditAction, record_user_audit_event
from services.users.utils import get_user_or_raise


async def delete_user(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    user_id: UUID,
) -> None:
    if actor.id == user_id:
        raise AppValidationError("You cannot delete your own user account", field="user_id")

    user = await get_user_or_raise(db, user_id=user_id)
    user.soft_delete(deleted_by=actor.id, cascade=False)
    await session_manager.revoke_user_sessions(db, user_id=str(user.id))
    await db.flush()
    await record_user_audit_event(
        db,
        action=AuditAction.DELETE,
        user=user,
        actor=actor,
        request=request,
        details={"source": "admin"},
    )
