# apps/api/services/integrations/connections/update_resource_selection.py

"""Replace the enabled resource selection for one integration connection."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationConnectionError, IntegrationValidationError
from models.integrations import IntegrationResource
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.recompute_connection_status import (
    recompute_connection_status,
)
from services.integrations.connections.schemas import (
    ResourceSelectionRequest,
    ResourceSelectionResponse,
)
from services.integrations.connections.utils import (
    get_visible_connection,
    require_connection_mutation_allowed,
)
from services.integrations.domain import CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS
from services.integrations.enqueue_metadata_sync import enqueue_metadata_sync
from services.integrations.utils import record_integration_audit


async def update_resource_selection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: ResourceSelectionRequest,
) -> ResourceSelectionResponse:
    """Apply a validated replace-set and recompute the connection status."""
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    require_connection_mutation_allowed(connection, actor=actor, membership=membership)
    if connection.status in CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS:
        raise IntegrationConnectionError(
            "Connection credentials must be ready before resource selection",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="update_resource_selection",
        )

    resources = (
        await db.scalars(
            select(IntegrationResource)
            .where(
                IntegrationResource.connection_id == connection.id,
                IntegrationResource.deleted.is_(False),
            )
            .with_for_update()
        )
    ).all()
    requested_ids = set(payload.enabled_resource_ids)
    resources_by_id = {resource.id: resource for resource in resources}
    invalid_ids = requested_ids - resources_by_id.keys()
    removed_ids = {
        resource_id
        for resource_id in requested_ids
        if resource_id in resources_by_id and resources_by_id[resource_id].availability == "removed"
    }
    if invalid_ids or removed_ids:
        raise IntegrationValidationError(
            "Selected resources must be available on this connection",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="update_resource_selection",
        )

    previously_enabled = {resource.id for resource in resources if resource.enabled}
    for resource in resources:
        resource.enabled = resource.id in requested_ids
    await db.flush()

    added = sorted(requested_ids - previously_enabled, key=str)
    removed = sorted(previously_enabled - requested_ids, key=str)
    await record_integration_audit(
        db,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_RESOURCE,
        resource_id=connection.id,
        details={
            "enabled_added": [str(resource_id) for resource_id in added],
            "enabled_removed": [str(resource_id) for resource_id in removed],
        },
    )
    await recompute_connection_status(db, connection)
    await enqueue_metadata_sync(
        db,
        connection=connection,
        initiated_by_user_id=actor.id,
    )
    return ResourceSelectionResponse(
        connection_id=connection.id,
        enabled_resource_ids=sorted(requested_ids, key=str),
        status=connection.status,
    )
