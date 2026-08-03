# apps/api/services/auth/totp/setup_totp.py

"""Set up TOTP for the current user."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthenticationError
from core.exceptions.general import ConflictError
from models.user import User
from services.auth.schemas import TotpSetupRequest, TotpSetupResponse
from services.auth.utils import record_auth_security_event
from services.security import SecurityEventType

from .utils import create_totp_enrollment_token, require_totp_enrollment_step_up


async def setup_totp(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    payload: TotpSetupRequest,
) -> TotpSetupResponse:
    if user.totp_enabled:
        raise ConflictError("TOTP is already enabled", conflicting_resource="totp")

    try:
        await require_totp_enrollment_step_up(
            db,
            request=request,
            user=user,
            current_password=payload.current_password,
        )
    except AuthenticationError:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_TOTP_FAILED,
            request=request,
            user_email=user.email,
            details={"reason": "setup_step_up_failed"},
            committed=True,
        )
        raise

    secret = user.generate_totp_secret()
    enrollment_token = create_totp_enrollment_token(user=user, secret=secret)
    await db.flush()
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_TOTP_CHALLENGE_CREATED,
        request=request,
        user_email=user.email,
        details={"purpose": "setup"},
    )
    return TotpSetupResponse(
        provisioning_uri=user.get_totp_qr_uri(),
        secret=secret,
        enrollment_token=enrollment_token,
    )
