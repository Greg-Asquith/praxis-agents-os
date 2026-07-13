# apps/api/services/integrations/oauth/utils.py

"""Signed state, PKCE, and purpose-separated verifier encryption helpers."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlparse
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError, IntegrationConnectionError
from core.settings import settings
from services.integrations.utils import ensure_credential_keys_loaded
from utils.security import derive_purpose_key

OAUTH_STATE_TYPE: Final = "integration_oauth_state"
PKCE_VERIFIER_PURPOSE: Final = "praxis:oauth-pkce-verifier:v1"


def create_integration_oauth_state(
    *,
    connection_id: UUID,
    provider_key: str,
    owner_scope: str,
    workspace_id: UUID,
    user_id: UUID,
    next_path: str | None,
) -> tuple[str, dict[str, Any]]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "type": OAUTH_STATE_TYPE,
        "connection_id": str(connection_id),
        "provider_key": provider_key,
        "owner_scope": owner_scope,
        "workspace_id": str(workspace_id),
        "user_id": str(user_id),
        "next_path": safe_next_path(next_path),
        "jti": secrets.token_urlsafe(24),
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.INTEGRATIONS_OAUTH_STATE_TTL_MINUTES)).timestamp()
        ),
    }
    token = jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")
    return token, payload


def verify_integration_oauth_state(state: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            state,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError) as exc:
        raise _invalid_state(exc) from exc

    required = {
        "connection_id",
        "provider_key",
        "owner_scope",
        "workspace_id",
        "user_id",
        "jti",
        "iat",
        "exp",
    }
    if payload.get("type") != OAUTH_STATE_TYPE or any(not payload.get(key) for key in required):
        raise _invalid_state()
    if payload["owner_scope"] not in {"user", "workspace"}:
        raise _invalid_state()
    try:
        UUID(str(payload["connection_id"]))
        UUID(str(payload["workspace_id"]))
        UUID(str(payload["user_id"]))
    except ValueError as exc:
        raise _invalid_state(exc) from exc
    payload["next_path"] = safe_next_path(payload.get("next_path"))
    return payload


def safe_next_path(next_path: str | None) -> str | None:
    if not next_path:
        return None
    parsed = urlparse(next_path)
    if parsed.scheme or parsed.netloc or not next_path.startswith("/"):
        return None
    return next_path


def generate_code_verifier() -> str:
    """Generate an RFC 7636 verifier in the required 43-128 character range."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def parse_oauth_json_object(
    response: Any,
    *,
    provider_key: str,
    operation: str,
) -> dict[str, Any]:
    """Decode an OAuth response without leaking transport parsing errors."""
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise IntegrationConnectionError(
            "Integration provider returned an invalid JSON response",
            provider_key=provider_key,
            operation=operation,
            original_error=exc,
        ) from exc
    if not isinstance(payload, dict):
        raise IntegrationConnectionError(
            "Integration provider returned an unexpected response",
            provider_key=provider_key,
            operation=operation,
        )
    return payload


async def encrypt_code_verifier(db: AsyncSession, verifier: str) -> str:
    return (await _verifier_fernet(db)).encrypt(verifier.encode()).decode("ascii")


async def decrypt_code_verifier(db: AsyncSession, ciphertext: str) -> str:
    try:
        return (await _verifier_fernet(db)).decrypt(ciphertext.encode("ascii")).decode()
    except InvalidToken as exc:
        raise IntegrationAuthError(
            "OAuth PKCE verifier could not be decrypted",
            operation="oauth_state",
            original_error=exc,
        ) from exc


async def _verifier_fernet(db: AsyncSession) -> MultiFernet:
    roots = await ensure_credential_keys_loaded(db)
    instances = []
    for root in roots:
        decoded = base64.urlsafe_b64decode(root.encode("ascii"))
        derived = derive_purpose_key(decoded, PKCE_VERIFIER_PURPOSE)
        instances.append(Fernet(base64.urlsafe_b64encode(derived)))
    return MultiFernet(instances)


def _invalid_state(original_error: Exception | None = None) -> IntegrationAuthError:
    return IntegrationAuthError(
        "Integration OAuth state is invalid",
        operation="oauth_state",
        original_error=original_error,
    )
