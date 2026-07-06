# apps/api/services/auth/login_with_password.py

"""Authenticate a user with email/password auth."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthenticationError, AuthorizationError
from core.settings import settings
from services.auth.schemas import AuthResponse, LoginRequest
from services.auth.utils import (
    get_user_by_email,
    issue_auth_response,
    record_auth_security_event,
    record_failed_login_attempt,
)
from services.security import SecurityEventType
from services.workspaces.provisioning import provision_personal_workspace
from utils.validation import normalize_email


async def login_with_password(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    payload: LoginRequest,
) -> AuthResponse:
    if not settings.EMAIL_AUTH_ENABLED:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_LOGIN_FAILED,
            request=request,
            user_email=payload.email,
            details={"reason": "email_auth_disabled"},
            committed=True,
        )
        raise AuthorizationError("Email authentication is disabled")

    email = normalize_email(payload.email)
    user = await get_user_by_email(db, email)
    if not user:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_LOGIN_FAILED,
            request=request,
            user_email=email,
            details={"reason": "invalid_credentials"},
            committed=True,
        )
        raise AuthenticationError("Invalid email or password")

    if user.is_locked:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_LOGIN_FAILED,
            request=request,
            user_email=email,
            details={"reason": "account_locked", "locked_until": user.locked_until},
            committed=True,
        )
        raise AuthenticationError("Account is temporarily locked")

    if (
        not user.is_active
        or user.deleted
        or not user.has_password
        or not user.verify_password(payload.password)
    ):
        await record_failed_login_attempt(
            user_id=user.id,
            reason="invalid_credentials",
            request=request,
            user_email=email,
        )
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_LOGIN_FAILED,
            request=request,
            user_email=email,
            details={"reason": "invalid_credentials", "user_id": str(user.id)},
            committed=True,
        )
        raise AuthenticationError("Invalid email or password")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.lockout_reason = None
    if user.default_workspace_id is None:
        await provision_personal_workspace(db, user)

    event_type = (
        SecurityEventType.AUTH_TOTP_CHALLENGE_CREATED
        if user.totp_enabled
        else SecurityEventType.AUTH_LOGIN_SUCCEEDED
    )
    return await issue_auth_response(
        db,
        request=request,
        response=response,
        user=user,
        event_type=event_type,
        details={"method": "password", "requires_twofa": user.totp_enabled},
        require_twofa=user.totp_enabled,
    )
