# apps/api/services/secrets/write_secret.py

"""Write a new secret version and audit only its reference identity."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)
from services.secrets.domain import SecretReference
from services.secrets.factory import get_secrets_provider


async def write_secret(
    db: AsyncSession,
    *,
    name: str,
    value: str,
    workspace_id: UUID | None = None,
    actor_id: UUID | None = None,
) -> SecretReference:
    ref = await get_secrets_provider().write_secret(name, value)
    await safe_record_operation_audit_event(
        db,
        workspace_id=workspace_id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.SECRET_REFERENCE,
        actor_type=AuditActorType.USER if actor_id else AuditActorType.SERVICE,
        actor_id=actor_id,
        requested_by_user_id=actor_id,
        details={"reference": ref.render()},
    )
    return ref
