# apps/api/services/integrations/credentials/store_oauth_credential.py

"""Persist encrypted OAuth material for an external principal."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.integrations import ExternalCredential
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.utils import (
    compute_principal_fingerprint,
    credential_encryption_key_id,
    ensure_credential_keys_loaded,
    record_integration_audit,
)


async def store_oauth_credential(
    db: AsyncSession,
    *,
    provider_key: str,
    token_payload: dict[str, Any],
    external_principal_id: str,
    external_principal_label: str | None,
    granted_scopes: list[str] | tuple[str, ...],
) -> ExternalCredential:
    await ensure_credential_keys_loaded(db)
    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise IntegrationAuthError(
            "OAuth token response did not include an access token",
            provider_key=provider_key,
            operation="store_oauth_credential",
        )
    credential = ExternalCredential(
        provider_key=provider_key,
        auth_mode="oauth",
        principal_fingerprint=compute_principal_fingerprint(provider_key, external_principal_id),
        external_principal_label=external_principal_label,
        token_type=token_payload.get("token_type"),
        granted_scopes=list(granted_scopes),
        token_expires_at=_token_expiry(token_payload),
        encryption_key_id=credential_encryption_key_id(),
    )
    credential.access_token = access_token
    refresh_token = token_payload.get("refresh_token")
    credential.refresh_token = refresh_token if isinstance(refresh_token, str) else None
    db.add(credential)
    await db.flush()
    await record_integration_audit(
        db,
        workspace_id=None,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.INTEGRATION_CREDENTIAL,
        resource_id=credential.id,
        details={
            "provider_key": provider_key,
            "principal_fingerprint": credential.principal_fingerprint,
            "scopes": list(granted_scopes),
        },
    )
    return credential


def _token_expiry(token_payload: dict[str, Any]) -> datetime | None:
    expires_at = token_payload.get("expires_at")
    if isinstance(expires_at, datetime):
        return expires_at
    expires_in = token_payload.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return datetime.now(UTC) + timedelta(seconds=expires_in)
    return None
