# apps/api/services/auth/oauth/utils.py

"""Service-specific helpers for auth operations."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import jwt
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.auth import AuthenticationError, AuthorizationError
from core.exceptions.oauth import OAuthAuthenticationError, OAuthConfigurationError
from core.settings import settings
from models.user import User, UserAuth
from services.audit_events import (
    AuditAction,
    AuditResourceType,
    record_user_audit_event,
)
from services.auth.utils import get_user_by_email
from services.workspaces.provisioning import provision_personal_workspace
from utils.validation import normalize_email

logger = logging.getLogger(__name__)

_OAUTH_STATE_TTL = timedelta(minutes=10)

async def upsert_oauth_user(
    db: AsyncSession,
    *,
    provider_name: str,
    token_payload: dict[str, Any],
    profile: dict[str, Any],
    request: Request,
) -> User:
    provider_user_id = provider_user_id_from_profile(provider_name, profile)
    email = provider_email(provider_name, profile)
    if not provider_user_id:
        raise OAuthAuthenticationError(
            "OAuth provider did not return a stable user ID",
            provider=provider_name,
            endpoint="user_info",
        )
    if not email:
        raise OAuthAuthenticationError(
            "OAuth provider did not return a verified email",
            provider=provider_name,
            endpoint="user_info",
        )

    result = await db.execute(
        select(UserAuth)
        .options(selectinload(UserAuth.user))
        .where(
            UserAuth.provider == provider_name,
            UserAuth.provider_user_id == provider_user_id,
            UserAuth.deleted.is_(False),
        )
        .with_for_update()
    )
    auth_record = result.scalar_one_or_none()
    user = auth_record.user if auth_record else await get_user_by_email(db, email)

    created_user = False
    if user is None:
        if not settings.ALLOW_SIGNUP:
            raise AuthorizationError("Signup is disabled")
        user = User(
            email=email,
            display_name=provider_display_name(provider_name, profile),
            avatar_url=provider_avatar_url(profile),
            is_active=True,
        )
        db.add(user)
        await db.flush()
        workspace = await provision_personal_workspace(db, user)
        created_user = True
        await record_user_audit_event(
            db,
            action=AuditAction.CREATE,
            user=user,
            actor=user,
            workspace_id=workspace.id,
            details={"source": "oauth", "provider": provider_name},
            request=request,
        )

    if user.deleted or not user.is_active:
        raise AuthenticationError("User account is disabled")

    if not user.display_name:
        user.display_name = provider_display_name(provider_name, profile)
    if user.avatar_object_key is None and not user.avatar_url:
        user.avatar_url = provider_avatar_url(profile)

    if auth_record is None:
        auth_record = UserAuth(
            user_id=user.id,
            provider=provider_name,
            provider_user_id=provider_user_id,
            email=email,
            email_verified=provider_email_verified(provider_name, profile),
            raw_profile=profile,
        )
        db.add(auth_record)
        audit_action = AuditAction.CREATE
    else:
        auth_record.email = email
        auth_record.email_verified = provider_email_verified(provider_name, profile)
        auth_record.raw_profile = profile
        audit_action = AuditAction.UPDATE

    auth_record.access_token = str(token_payload.get("access_token") or "")
    refresh_token = token_payload.get("refresh_token")
    if refresh_token:
        auth_record.refresh_token = str(refresh_token)
    auth_record.token_expires_at = token_expires_at(token_payload)

    await db.flush()
    await record_user_audit_event(
        db,
        action=audit_action,
        user=user,
        actor=user,
        resource_type=AuditResourceType.USER_AUTH,
        details={"provider": provider_name, "created_user": created_user},
        request=request,
    )
    return user

def create_oauth_state(
    *,
    provider_name: str,
    redirect_uri: str,
    next_path: str | None,
) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + _OAUTH_STATE_TTL
    payload = {
        "type": "oauth_state",
        "provider": provider_name,
        "redirect_uri": redirect_uri,
        "next_path": safe_next_path(next_path),
        "jti": secrets.token_urlsafe(24),
        "exp": int(expires_at.timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")
    return token, expires_at


def create_oauth_link_state(
    *,
    provider_name: str,
    redirect_uri: str,
    user_id: Any,
    next_path: str | None,
) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + _OAUTH_STATE_TTL
    payload = {
        "type": "oauth_link_state",
        "provider": provider_name,
        "redirect_uri": redirect_uri,
        "user_id": str(user_id),
        "next_path": safe_next_path(next_path),
        "jti": secrets.token_urlsafe(24),
        "exp": int(expires_at.timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")
    return token, expires_at


def verify_oauth_link_state(state: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            state,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError as exc:
        raise OAuthAuthenticationError(
            "OAuth state has expired", provider="unknown", endpoint="state"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise OAuthAuthenticationError(
            "OAuth state is invalid", provider="unknown", endpoint="state"
        ) from exc

    if payload.get("type") != "oauth_link_state":
        raise OAuthAuthenticationError(
            "OAuth state is invalid",
            provider=str(payload.get("provider") or "unknown"),
            endpoint="state",
        )
    if not payload.get("provider") or not payload.get("redirect_uri") or not payload.get("user_id"):
        raise OAuthAuthenticationError(
            "OAuth state is incomplete",
            provider=str(payload.get("provider") or "unknown"),
            endpoint="state",
        )
    return payload


def verify_oauth_state(state: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            state,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError as exc:
        raise OAuthAuthenticationError(
            "OAuth state has expired", provider="unknown", endpoint="state"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise OAuthAuthenticationError(
            "OAuth state is invalid", provider="unknown", endpoint="state"
        ) from exc

    if payload.get("type") != "oauth_state":
        raise OAuthAuthenticationError(
            "OAuth state is invalid",
            provider=str(payload.get("provider") or "unknown"),
            endpoint="state",
        )
    if not payload.get("provider") or not payload.get("redirect_uri"):
        raise OAuthAuthenticationError(
            "OAuth state is incomplete",
            provider=str(payload.get("provider") or "unknown"),
            endpoint="state",
        )
    return payload


def resolve_provider_redirect_uri(provider_name: str, supplied_redirect_uri: str | None) -> str:
    configured = {
        "google": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "github": settings.GITHUB_OAUTH_REDIRECT_URI,
        "microsoft": settings.MICROSOFT_OAUTH_REDIRECT_URI,
    }.get(provider_name)
    if not configured:
        raise OAuthConfigurationError("OAuth provider redirect URI is not configured", provider_name)

    configured = configured.rstrip("/")
    if supplied_redirect_uri and supplied_redirect_uri.rstrip("/") != configured:
        raise OAuthAuthenticationError(
            "OAuth redirect URI is not allowed", provider=provider_name, endpoint="state"
        )
    return configured


def safe_next_path(next_path: str | None) -> str | None:
    if not next_path:
        return None
    parsed = urlparse(next_path)
    if parsed.scheme or parsed.netloc or not next_path.startswith("/"):
        return None
    return next_path


def provider_user_id_from_profile(provider_name: str, profile: dict[str, Any]) -> str | None:
    value = profile.get("id") or profile.get("sub")
    if value is None and provider_name == "github":
        value = profile.get("node_id")
    return str(value) if value is not None else None


def provider_email(provider_name: str, profile: dict[str, Any]) -> str | None:
    value = profile.get("email")
    if not value and provider_name == "microsoft":
        value = profile.get("mail") or profile.get("userPrincipalName")
    if not value:
        return None
    return normalize_email(str(value))


def provider_email_verified(provider_name: str, profile: dict[str, Any]) -> bool:
    if provider_name == "google":
        return bool(profile.get("verified_email") or profile.get("email_verified"))
    if provider_name == "github":
        return bool(profile.get("email"))
    if provider_name == "microsoft":
        return bool(provider_email(provider_name, profile))
    return False


def provider_display_name(provider_name: str, profile: dict[str, Any]) -> str | None:
    value = profile.get("name") or profile.get("displayName")
    if not value and provider_name == "github":
        value = profile.get("login")
    return str(value).strip() if value else None


def provider_avatar_url(profile: dict[str, Any]) -> str | None:
    value = profile.get("picture") or profile.get("avatar_url")
    return str(value).strip() if value else None


def token_expires_at(token_payload: dict[str, Any]) -> datetime | None:
    expires_in = token_payload.get("expires_in")
    if expires_in is None:
        return None
    try:
        return datetime.now(UTC) + timedelta(seconds=int(expires_in))
    except (TypeError, ValueError):
        return None
