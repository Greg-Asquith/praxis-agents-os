# apps/api/services/auth/totp/verify_totp.py

"""Verify TOTP and upgrade a partial session."""

from uuid import UUID

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.exceptions.auth import AuthenticationError
from core.rate_limiting import record_login_failure
from models.user import User
from services.auth.schemas import AuthResponse, AuthSession, TotpVerifyRequest
from services.auth.utils import (
    build_auth_user,
    enforce_login_failure_limit,
    record_and_enforce_login_failure,
    record_auth_security_event,
    record_failed_login_attempt,
    request_ip,
    session_token_from_request,
    set_auth_cookies,
)
from services.security import SecurityEventType
from services.workspaces.invitations import accept_pending_invitations_for_user

from .utils import verify_and_consume_login_second_factor


async def verify_totp(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    payload: TotpVerifyRequest,
) -> AuthResponse:
    client_ip = request_ip(request)
    session_token = session_token_from_request(request)
    if not session_token:
        await record_and_enforce_login_failure(
            request,
            None,
            anonymous_scope="totp",
        )
        raise AuthenticationError("No partial session")

    partial_info = await session_manager.get_partial_session_info(db, session_token)
    if not partial_info:
        await record_and_enforce_login_failure(
            request,
            None,
            anonymous_scope="totp",
        )
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_TOTP_FAILED,
            request=request,
            details={"reason": "partial_session_not_found"},
            committed=True,
        )
        raise AuthenticationError("Invalid or expired partial session")

    user = await db.get(User, UUID(partial_info["user_id"]))
    if not user or user.deleted or not user.is_active:
        await record_and_enforce_login_failure(
            request,
            None,
            anonymous_scope="totp",
        )
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_TOTP_FAILED,
            request=request,
            details={"reason": "user_not_found"},
            committed=True,
        )
        raise AuthenticationError("Invalid or expired partial session")

    await enforce_login_failure_limit(request, user.email)

    if not await verify_and_consume_login_second_factor(
        db,
        user=user,
        token=payload.token,
        backup_code=payload.backup_code,
    ):
        await record_login_failure(client_ip, user.email)
        await record_failed_login_attempt(
            user_id=user.id,
            reason="invalid_totp",
            request=request,
            user_email=user.email,
            revoke_partial_sessions_on_lock=True,
        )
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_TOTP_FAILED,
            request=request,
            user_email=user.email,
            details={"reason": "invalid_token"},
            committed=True,
        )
        raise AuthenticationError("Invalid TOTP code")

    upgraded = await session_manager.upgrade_partial_session(db, session_token)
    if not upgraded:
        raise AuthenticationError("Invalid or expired partial session")

    set_auth_cookies(
        response,
        session_token=upgraded["session_token"],
        expires_at=upgraded["expires_at"],
    )
    await record_auth_security_event(
        db=db,
        event_type=SecurityEventType.AUTH_TOTP_VERIFIED,
        request=request,
        user_email=user.email,
        details={"session_id": upgraded["session_id"]},
    )
    # Password/OAuth full sessions accept invites in issue_auth_response; TOTP upgrades here.
    await accept_pending_invitations_for_user(db, user=user, request=request)
    return AuthResponse(
        user=await build_auth_user(db, user),
        session=AuthSession(expires_at=upgraded["expires_at"], twofa_verified=True),
        requires_twofa=False,
    )
