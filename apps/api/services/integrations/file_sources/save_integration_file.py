# apps/api/services/integrations/file_sources/save_integration_file.py

"""Save one provider file into Files as the signed-in person, with no agent turn."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import record_operation_audit_event
from services.integrations.file_sources.schemas import (
    IntegrationFileSaveRead,
    IntegrationFileSourceCreate,
)
from services.integrations.file_sources.utils import (
    record_file_request_failure,
    resolve_file_request,
    source_identity,
)
from services.integrations.files.create_copy import create_copy


async def save_integration_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    payload: IntegrationFileSourceCreate,
) -> IntegrationFileSaveRead:
    """Agent tool policies don't apply: the person saves with their own connection."""
    definition, file_request = await resolve_file_request(
        db, actor=actor, workspace=workspace, conversation_id=conversation_id, payload=payload
    )
    try:
        download = await definition.download(db, file_request)
        saved = await create_copy(
            db,
            workspace=workspace,
            user=actor,
            conversation_id=conversation_id,
            name=download.name,
            content=download.content,
            content_type=download.content_type,
        )
        await record_operation_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.CREATE,
            resource_type=AuditResourceType.FILE,
            resource_id=saved.file.id,
            actor_type=AuditActorType.USER,
            actor_id=actor.id,
            actor_display=actor.email,
            requested_by_user_id=actor.id,
            details={
                "operation": definition.operation,
                "provider_key": payload.provider_key,
                "conversation_id": str(conversation_id),
                "revision_id": str(saved.revision.id),
                "source": source_identity(file_request),
            },
        )
        result = IntegrationFileSaveRead(
            file_id=saved.file.id,
            name=saved.file.name,
            content_type=saved.file.content_type,
            size_bytes=saved.bytes_written,
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        await record_file_request_failure(
            request=file_request,
            action=AuditAction.CREATE,
            operation=definition.operation,
            conversation_id=conversation_id,
            exc=exc,
        )
        raise
    return result
