# apps/api/services/auth/disable_totp.py

"""Disable TOTP for the current user."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthenticationError
from models.user import User
from services.audit_events import AuditAction, AuditResourceType, record_user_audit_event
from services.auth.schemas import MessageResponse, TotpDisableRequest
from services.auth.utils import record_auth_security_event, verify_totp_or_backup
from services.security import SecurityEventType


async def disable_totp(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    payload: TotpDisableRequest,
) -> MessageResponse:
    if not user.totp_enabled:
        return MessageResponse(message="TOTP is not enabled")

    if not verify_totp_or_backup(user, token=payload.token, backup_code=payload.backup_code):
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_TOTP_FAILED,
            request=request,
            user_email=user.email,
            details={"reason": "disable_invalid_token"},
            committed=True,
        )
        raise AuthenticationError("Invalid TOTP code")

    user.disable_totp()
    await db.flush()
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_TOTP_DISABLED,
        request=request,
        user_email=user.email,
        details={},
    )
    await record_user_audit_event(
        db,
        action=AuditAction.DISABLE,
        user=user,
        actor=user,
        resource_type=AuditResourceType.USER_AUTH,
        details={"method": "totp"},
        request=request,
    )
    return MessageResponse(message="TOTP disabled")
