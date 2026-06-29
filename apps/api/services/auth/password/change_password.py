# apps/api/services/auth/change_password.py

"""Change the current user's password."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.exceptions.auth import AuthenticationError
from models.user import User
from services.audit_events import AuditAction, record_user_audit_event
from services.auth.schemas import MessageResponse, PasswordChangeRequest
from services.auth.utils import record_auth_security_event, session_token_from_request
from services.security import SecurityEventType
from utils.validation import validate_password_strength


async def change_password(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    payload: PasswordChangeRequest,
) -> MessageResponse:
    validate_password_strength(payload.new_password)
    if not user.has_password or not user.verify_password(payload.current_password):
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_LOGIN_FAILED,
            request=request,
            user_email=user.email,
            details={"reason": "password_change_invalid_current_password"},
            committed=True,
        )
        raise AuthenticationError("Current password is incorrect")

    user.set_password(payload.new_password)
    current_session_token = session_token_from_request(request)
    revoked_count = await session_manager.revoke_user_sessions(
        db,
        str(user.id),
        exclude_session_token=current_session_token,
    )
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_PASSWORD_CHANGED,
        request=request,
        user_email=user.email,
        details={"revoked_sessions": revoked_count},
    )
    await record_user_audit_event(
        db,
        action=AuditAction.UPDATE,
        user=user,
        actor=user,
        details={"field": "password", "revoked_sessions": revoked_count},
        request=request,
    )
    return MessageResponse(message="Password changed")
