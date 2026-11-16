# apps/api/services/integrations/file_sources/utils.py

"""Resolves a person's provider file request and records its failures."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.user import User
from models.workspace import Workspace
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_independent_operation_audit_event,
)
from services.integrations.context import resolve_conversation_target
from services.integrations.file_sources.schemas import IntegrationFileSourceCreate
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    IntegrationFileRequest,
    IntegrationFileSourceDefinition,
)


async def resolve_file_request(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    payload: IntegrationFileSourceCreate,
) -> tuple[IntegrationFileSourceDefinition, IntegrationFileRequest]:
    """Fails before credentials unless the reference names a target selected in the conversation."""
    definition = _file_source_definition(payload)
    try:
        reference = definition.reference_model.model_validate(payload.reference)
    except ValidationError:
        raise IntegrationValidationError(
            "The file reference is invalid for this provider",
            provider_key=payload.provider_key,
            operation=definition.operation,
        ) from None
    scope = await resolve_conversation_target(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        provider_key=payload.provider_key,
        scope_id=reference.provider_scope_id,
        operation=definition.operation,
    )
    return definition, IntegrationFileRequest(
        reference=reference, scope=scope, actor=actor, workspace=workspace
    )


def source_identity(request: IntegrationFileRequest) -> dict[str, str]:
    """Identity fields only; audits never carry bytes, labels, or connection IDs."""
    reference = request.reference
    return dict(zip(reference.identity_fields, reference.identity(), strict=True))


async def record_file_request_failure(
    *,
    request: IntegrationFileRequest,
    action: AuditAction,
    provider_key: str,
    conversation_id: UUID,
    exc: Exception,
) -> None:
    await safe_record_independent_operation_audit_event(
        workspace_id=request.workspace.id,
        action=action,
        resource_type=AuditResourceType.FILE,
        actor_type=AuditActorType.USER,
        actor_id=request.actor.id,
        actor_display=request.actor.email,
        requested_by_user_id=request.actor.id,
        status=AuditStatus.FAILURE,
        details={
            "provider_key": provider_key,
            "conversation_id": str(conversation_id),
            "source": source_identity(request),
            "error_code": getattr(exc, "error_code", None) or exc.__class__.__name__,
        },
        request=None,
    )


def _file_source_definition(
    payload: IntegrationFileSourceCreate,
) -> IntegrationFileSourceDefinition:
    plugin = PROVIDER_PLUGINS.get(payload.provider_key)
    entity_kind = payload.reference.get("entity_kind")
    for definition in plugin.file_source_definitions if plugin else ():
        if definition.entity_kind == entity_kind:
            return definition
    raise IntegrationValidationError(
        "This provider file can't be opened here",
        provider_key=payload.provider_key,
        operation="file_source",
    )
