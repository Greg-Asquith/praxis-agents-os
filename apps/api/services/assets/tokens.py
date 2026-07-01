# apps/api/services/assets/tokens.py

"""Short-lived signed tokens for asset upload confirmation."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pydantic import ValidationError

from core.exceptions.auth import AuthorizationError
from core.settings import settings
from services.assets.domain import AssetKind, AssetUploadTokenPayload
from services.storage.domain import StorageBucket, StorageObjectRef

_ASSET_UPLOAD_TOKEN_TYPE = "asset_upload"
_ASSET_UPLOAD_TOKEN_TTL = timedelta(minutes=10)


def create_asset_upload_token(
    *,
    kind: AssetKind,
    actor_user_id: UUID,
    ref: StorageObjectRef,
    content_type: str,
    max_size_bytes: int,
    target_user_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> tuple[str, datetime]:
    """Create a short-lived API token that binds a signed upload to one asset."""
    now = datetime.now(UTC)
    expires_at = now + _ASSET_UPLOAD_TOKEN_TTL
    payload = {
        "type": _ASSET_UPLOAD_TOKEN_TYPE,
        "kind": kind.value,
        "actor_user_id": str(actor_user_id),
        "target_user_id": str(target_user_id) if target_user_id else None,
        "workspace_id": str(workspace_id) if workspace_id else None,
        "bucket": ref.bucket.value,
        "object_key": ref.key,
        "content_type": content_type,
        "max_size_bytes": max_size_bytes,
        "jti": secrets.token_urlsafe(24),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY.get_secret_value(), algorithm="HS256")
    return token, expires_at


def verify_asset_upload_token(
    token: str,
    *,
    expected_kind: AssetKind,
    actor_user_id: UUID,
    target_user_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> AssetUploadTokenPayload:
    """Decode and validate an asset upload confirmation token."""
    try:
        raw_payload = jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=["HS256"],
        )
        payload = AssetUploadTokenPayload.model_validate(raw_payload)
    except jwt.ExpiredSignatureError as exc:
        raise AuthorizationError("Asset upload token has expired") from exc
    except (jwt.InvalidTokenError, ValidationError) as exc:
        raise AuthorizationError("Asset upload token is invalid") from exc

    if payload.token_type != _ASSET_UPLOAD_TOKEN_TYPE or payload.kind != expected_kind:
        raise AuthorizationError("Asset upload token is invalid")
    if payload.actor_user_id != actor_user_id:
        raise AuthorizationError("Asset upload token is not valid for this user")
    if target_user_id is not None and payload.target_user_id != target_user_id:
        raise AuthorizationError("Asset upload token is not valid for this user")
    if workspace_id is not None and payload.workspace_id != workspace_id:
        raise AuthorizationError("Asset upload token is not valid for this workspace")
    return payload


def token_ref(payload: AssetUploadTokenPayload) -> StorageObjectRef:
    """Return the storage ref bound into a validated upload token."""
    return StorageObjectRef(bucket=StorageBucket(payload.bucket), key=payload.object_key)
