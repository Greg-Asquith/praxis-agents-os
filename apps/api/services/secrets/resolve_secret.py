# apps/api/services/secrets/resolve_secret.py

"""Resolve a secret reference, auditing failures without exposing values."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_independent_operation_audit_event,
)
from services.secrets.domain import SecretReference
from services.secrets.factory import get_secrets_provider


async def resolve_secret(
    db: AsyncSession,
    ref: SecretReference,
    *,
    workspace_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> str:
    try:
        provider = get_secrets_provider()
        if ref.provider != provider.provider_key:
            raise IntegrationValidationError(
                "Secret reference provider does not match the configured provider",
                provider_key=provider.provider_key,
                operation="resolve_secret",
            )
        return await provider.resolve_secret(ref)
    except Exception:
        await safe_record_independent_operation_audit_event(
            workspace_id=workspace_id,
            action=AuditAction.READ,
            resource_type=AuditResourceType.SECRET_REFERENCE,
            actor_type=AuditActorType.USER if actor_id else AuditActorType.SERVICE,
            actor_id=actor_id,
            requested_by_user_id=actor_id,
            status=AuditStatus.FAILURE,
            details={"reference": ref.render()},
        )
        raise
