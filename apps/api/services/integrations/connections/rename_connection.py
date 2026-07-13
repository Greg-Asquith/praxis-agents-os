# apps/api/services/integrations/connections/rename_connection.py

"""Rename a visible integration connection."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.schemas import ConnectionRead, RenameConnectionRequest
from services.integrations.connections.utils import (
    connection_to_read,
    get_visible_connection,
    require_connection_mutation_allowed,
)
from services.integrations.utils import record_integration_audit


async def rename_connection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: RenameConnectionRequest,
) -> ConnectionRead:
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    require_connection_mutation_allowed(connection, actor=actor, membership=membership)
    label = payload.label.strip()
    if not label:
        raise IntegrationValidationError(
            "Connection label is required", operation="rename_connection"
        )
    old_label = connection.label
    connection.label = label
    await db.flush()
    await record_integration_audit(
        db,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        details={"old_label": old_label, "new_label": label},
    )
    return await connection_to_read(db, connection, include_credential=False)
