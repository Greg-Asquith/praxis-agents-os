# apps/api/services/integrations/credentials/store_secret_reference_credential.py

"""Persist a non-OAuth credential as a secret reference only."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integrations import ExternalCredential
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.utils import (
    compute_principal_fingerprint,
    ensure_credential_keys_loaded,
    record_integration_audit,
)
from services.secrets.domain import SecretReference


async def store_secret_reference_credential(
    db: AsyncSession,
    *,
    provider_key: str,
    auth_mode: str,
    secret_reference: SecretReference,
    external_principal_id: str | None = None,
    external_principal_label: str | None = None,
) -> ExternalCredential:
    if auth_mode not in {"api_key", "service_account", "system_token"}:
        raise IntegrationValidationError(
            "Secret-reference credentials require a non-OAuth authentication mode",
            provider_key=provider_key,
            operation="store_secret_reference_credential",
        )
    await ensure_credential_keys_loaded(db)
    credential = ExternalCredential(
        provider_key=provider_key,
        auth_mode=auth_mode,
        secret_provider=secret_reference.provider,
        secret_name=secret_reference.name,
        secret_version=secret_reference.version,
        principal_fingerprint=compute_principal_fingerprint(
            provider_key, external_principal_id or secret_reference.name
        ),
        external_principal_label=external_principal_label,
    )
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
            "auth_mode": auth_mode,
            "reference": secret_reference.render(),
            "principal_fingerprint": credential.principal_fingerprint,
        },
    )
    return credential
