# apps/api/services/auth/utils.py

"""Service-specific helpers for auth operations."""

import logging
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any
from uuid import UUID

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import get_async_db_session_factory
from core.dependencies import is_super_admin_email
from core.rate_limiting import get_client_ip
from core.settings import settings
from models.user import User
from services.auth.schemas import AuthResponse, AuthSession, AuthUser
from services.security import (
    SecurityEventType,
    safe_record_security_event,
    safe_record_security_event_committed,
)
from utils.security import generate_csrf_token

logger = logging.getLogger(__name__)

_OAUTH_STATE_TTL = timedelta(minutes=10)
_AUTH_USER_REFRESH_FIELDS = [
    "id",
    "email",
    "display_name",
    "avatar_url",
    "is_active",
    "default_workspace_id",
    "totp_enabled",
    "created_at",
    "updated_at",
]


async def build_auth_user(db: AsyncSession, user: User) -> AuthUser:
    """Return a public auth user after refreshing server-managed columns."""
    await db.flush()
    await db.refresh(user, attribute_names=_AUTH_USER_REFRESH_FIELDS)
    return AuthUser.from_user(user, is_super_admin=is_super_admin_email(user.email))


def set_auth_cookies(response: Response, *, session_token: str, expires_at: datetime) -> None:
    """Set the HTTP-only session cookie and matching readable CSRF cookie."""
    session_manager.set_session_cookie(response, session_token, expires_at)
    response.set_cookie(
        key="csrf",
        value=generate_csrf_token(session_token),
        httponly=False,
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        max_age=settings.SESSION_DURATION_DAYS * 24 * 60 * 60,
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    """Clear session and CSRF cookies."""
    session_manager.clear_session_cookie(response)
    response.delete_cookie(
        "csrf",
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
        samesite="lax",
        secure=settings.SECURE_COOKIES,
    )


async def issue_auth_response(
    db: AsyncSession,
    *,
    request: Request,
    response: Response,
    user: User,
    event_type: SecurityEventType,
    details: dict[str, Any],
    require_twofa: bool = False,
) -> AuthResponse:
    ip_address = request_ip(request)
    user_agent = request.headers.get("user-agent")
    session_result = (
        await session_manager.create_partial_session(
            db,
            str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if require_twofa
        else await session_manager.create_session(
            db,
            str(user.id),
            ip_address=ip_address,
            user_agent=user_agent,
            twofa_verified=True,
        )
    )
    set_auth_cookies(
        response,
        session_token=session_result["session_token"],
        expires_at=session_result["expires_at"],
    )
    await record_auth_security_event(
        db=db,
        event_type=event_type,
        request=request,
        user_email=user.email,
        details={**details, "session_id": session_result["session_id"]},
    )
    auth_user = None if require_twofa else await build_auth_user(db, user)
    return AuthResponse(
        user=auth_user,
        session=AuthSession(
            expires_at=session_result["expires_at"],
            twofa_verified=session_result["twofa_verified"],
        ),
        requires_twofa=require_twofa,
    )


async def record_failed_login_attempt(
    *,
    user_id: UUID,
    reason: str,
    request: Request,
    user_email: str | None = None,
) -> None:
    """Persist failed-attempt counters outside the 401 request transaction."""
    locked = False
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            result = await db.execute(select(User).where(User.id == user_id).with_for_update())
            user = result.scalar_one_or_none()
            if user is None:
                return

            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.SECURITY_SUSPICIOUS_ACTIVITY_THRESHOLD:
                user.locked_until = datetime.now(UTC) + timedelta(
                    minutes=settings.SECURITY_LOCKOUT_DURATION_MINUTES
                )
                user.lockout_reason = reason
                locked = True
            await db.commit()
    except Exception:
        logger.error("Failed to persist failed login attempt", exc_info=True)
        return

    if locked:
        await record_auth_security_event(
            event_type=SecurityEventType.AUTH_ACCOUNT_LOCKED,
            request=request,
            user_email=user_email,
            details={"reason": reason, "user_id": str(user_id)},
            committed=True,
        )


async def record_auth_security_event(
    *,
    event_type: SecurityEventType,
    request: Request,
    user_email: str | None = None,
    details: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    committed: bool = False,
) -> None:
    event_kwargs = {
        "event_type": event_type,
        "ip_address": request_ip(request),
        "endpoint": request.url.path,
        "user_email": user_email,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.scope.get("request_id") or request.headers.get("x-request-id"),
        "details": details or {},
    }
    if committed:
        await safe_record_security_event_committed(**event_kwargs)
        return
    if db is None:
        raise RuntimeError("db is required for request-scoped security events")
    await safe_record_security_event(db, **event_kwargs)


async def get_user_by_email(
    db: AsyncSession,
    email: str,
    *,
    include_deleted: bool = False,
) -> User | None:
    stmt = select(User).where(User.email == email)
    if not include_deleted:
        stmt = stmt.where(User.deleted.is_(False))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def verify_totp_or_backup(
    user: User,
    *,
    token: str | None,
    backup_code: str | None,
) -> bool:
    if token and user.verify_totp(token):
        return True
    return bool(backup_code and user.verify_backup_code(backup_code))


def request_ip(request: Request) -> str:
    candidate = get_client_ip(request)
    try:
        ip_address(candidate)
        return candidate
    except ValueError:
        return "127.0.0.1"


def session_token_from_request(request: Request) -> str | None:
    token = request.cookies.get("session")
    if token:
        return token

    authorization = request.headers.get("authorization") or ""
    scheme, _, credentials = authorization.partition(" ")
    if scheme.lower() == "bearer" and credentials:
        return credentials.strip()
    return None
