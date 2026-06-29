# apps/api/services/auth/setup_totp.py

"""Set up TOTP for the current user."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from services.auth.schemas import TotpSetupResponse
from services.auth.utils import record_auth_security_event
from services.security import SecurityEventType


async def setup_totp(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
) -> TotpSetupResponse:
    if user.totp_enabled:
        raise ConflictError("TOTP is already enabled", conflicting_resource="totp")

    secret = user.get_totp_secret() if user.totp_secret_encrypted else user.generate_totp_secret()
    await db.flush()
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_TOTP_CHALLENGE_CREATED,
        request=request,
        user_email=user.email,
        details={"purpose": "setup"},
    )
    return TotpSetupResponse(provisioning_uri=user.get_totp_qr_uri(), secret=secret)
