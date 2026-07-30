# apps/api/services/auth/totp/utils.py

"""Shared TOTP authentication helpers."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Request
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthenticationError
from core.exceptions.general import CustomValueError
from core.settings import settings
from models.session import Session
from models.user import User
from services.auth.utils import session_token_from_request
from utils.security import hash_token

_TOTP_ENROLLMENT_TOKEN_TYPE = "totp_enrollment"
_TOTP_ENROLLMENT_TTL = timedelta(minutes=10)


async def require_totp_enrollment_step_up(
    db: AsyncSession,
    *,
    request: Request,
    user: User,
    current_password: str | None,
) -> None:
    """Require the current password or a full session created by a recent login."""
    if current_password is not None:
        if user.has_password and user.verify_password(current_password):
            return
        raise AuthenticationError("Current password is incorrect")

    session_token = session_token_from_request(request)
    if not session_token:
        raise AuthenticationError("Recent authentication is required")

    try:
        token_hash = hash_token(session_token)
    except CustomValueError as exc:
        raise AuthenticationError("Recent authentication is required") from exc

    now = datetime.now(UTC)
    result = await db.execute(
        select(Session.id).where(
            Session.token_hash == token_hash,
            Session.user_id == user.id,
            Session.created_at >= now - _TOTP_ENROLLMENT_TTL,
            Session.expires_at > now,
            Session.twofa_verified.is_(True),
            Session.deleted.is_(False),
        )
    )
    if result.scalar_one_or_none() is None:
        raise AuthenticationError(
            "Recent authentication is required; sign in again before setting up two-factor authentication"
        )


def create_totp_enrollment_token(*, user: User, secret: str) -> str:
    """Create a short-lived grant bound to one user and one enrollment secret."""
    now = datetime.now(UTC)
    payload = {
        "type": _TOTP_ENROLLMENT_TOKEN_TYPE,
        "user_id": str(user.id),
        "secret_hash": hashlib.sha256(secret.encode()).hexdigest(),
        "jti": secrets.token_urlsafe(24),
        "iat": int(now.timestamp()),
        "exp": int((now + _TOTP_ENROLLMENT_TTL).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")


def verify_totp_enrollment_token(token: str, *, user: User, secret: str) -> None:
    """Require a valid enrollment grant for this user and current secret."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        raise AuthenticationError("TOTP enrollment authorization is invalid or expired") from exc

    expected_secret_hash = hashlib.sha256(secret.encode()).hexdigest()
    if (
        payload.get("type") != _TOTP_ENROLLMENT_TOKEN_TYPE
        or payload.get("user_id") != str(user.id)
        or not isinstance(payload.get("secret_hash"), str)
        or not secrets.compare_digest(payload["secret_hash"], expected_secret_hash)
    ):
        raise AuthenticationError("TOTP enrollment authorization is invalid or expired")


async def verify_and_consume_login_second_factor(
    db: AsyncSession,
    *,
    user: User,
    token: str | None,
    backup_code: str | None,
) -> bool:
    """Verify login TOTP with atomic replay protection, or consume a backup code."""
    if token:
        counter = user.matching_totp_counter(token)
        if counter is not None:
            result = await db.execute(
                update(User)
                .where(
                    User.id == user.id,
                    or_(
                        User.last_totp_counter.is_(None),
                        User.last_totp_counter < counter,
                    ),
                )
                .values(
                    last_totp_counter=counter,
                    failed_login_attempts=0,
                    locked_until=None,
                    lockout_reason=None,
                )
                .returning(User.id)
            )
            return result.scalar_one_or_none() is not None

    if backup_code and user.verify_backup_code(backup_code):
        user.failed_login_attempts = 0
        user.locked_until = None
        user.lockout_reason = None
        return True
    return False
