# apps/api/services/auth/enable_totp.py

"""Enable TOTP for the current user."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthenticationError
from core.exceptions.general import ConflictError
from models.user import User
from services.audit_events import AuditAction, AuditResourceType, record_user_audit_event
from services.auth.schemas import TotpEnableRequest, TotpEnableResponse
from services.auth.utils import record_auth_security_event
from services.security import SecurityEventType


async def enable_totp(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    payload: TotpEnableRequest,
) -> TotpEnableResponse:
    if user.totp_enabled:
        raise ConflictError("TOTP is already enabled", conflicting_resource="totp")
    if not user.totp_secret_encrypted:
        user.generate_totp_secret()

    if not user.verify_totp(payload.token):
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_TOTP_FAILED,
            request=request,
            user_email=user.email,
            details={"reason": "enable_invalid_token"},
            committed=True,
        )
        raise AuthenticationError("Invalid TOTP code")

    user.enable_totp()
    backup_codes = user.generate_backup_codes()
    await db.flush()
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_TOTP_ENABLED,
        request=request,
        user_email=user.email,
        details={},
    )
    await record_user_audit_event(
        db,
        action=AuditAction.ENABLE,
        user=user,
        actor=user,
        resource_type=AuditResourceType.USER_AUTH,
        details={"method": "totp"},
        request=request,
    )
    return TotpEnableResponse(message="TOTP enabled", backup_codes=backup_codes)
