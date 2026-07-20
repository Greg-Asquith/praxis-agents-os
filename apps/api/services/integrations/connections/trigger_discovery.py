# apps/api/services/integrations/connections/trigger_discovery.py

"""Request provider resource discovery for one visible connection."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.integrations.connections.schemas import DiscoveryTriggerResponse
from services.integrations.connections.utils import (
    get_visible_connection,
    require_connection_mutation_allowed,
)
from services.integrations.discovery import enqueue_discovery
from services.integrations.manifest import PROVIDER_MANIFESTS


async def trigger_discovery(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
) -> DiscoveryTriggerResponse:
    """Enqueue a deduplicated discovery job without provider I/O in the request."""
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    if connection.owner_user_id is not None:
        require_connection_mutation_allowed(connection, actor=actor, membership=membership)
    manifest = PROVIDER_MANIFESTS.get(connection.provider_key)
    if manifest is None or not manifest.requires_discovery:
        raise IntegrationValidationError(
            "This integration provider does not support resource discovery",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="trigger_discovery",
        )
    job = await enqueue_discovery(db, connection=connection)
    return DiscoveryTriggerResponse(job_id=job.id)
