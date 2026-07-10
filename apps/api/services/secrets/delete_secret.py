"""Delete a secret reference and audit only its reference identity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)
from services.secrets.domain import SecretReference
from services.secrets.factory import get_secrets_provider


async def delete_secret(
    db: AsyncSession,
    ref: SecretReference,
    *,
    workspace_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> bool:
    provider = get_secrets_provider()
    if ref.provider != provider.provider_key:
        raise IntegrationValidationError(
            "Secret reference provider does not match the configured provider",
            provider_key=provider.provider_key,
            operation="delete_secret",
        )
    deleted = await provider.delete_secret(ref)
    if deleted:
        await safe_record_operation_audit_event(
            db,
            workspace_id=workspace_id,
            action=AuditAction.DELETE,
            resource_type=AuditResourceType.SECRET_REFERENCE,
            actor_type=AuditActorType.USER if actor_id else AuditActorType.SERVICE,
            actor_id=actor_id,
            requested_by_user_id=actor_id,
            details={"reference": ref.render()},
        )
    return deleted
