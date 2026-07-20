# apps/api/services/integrations/connections/list_connection_resources.py

"""List discovered resources visible through one integration connection."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationResource
from models.user import User
from models.workspace import Workspace
from services.integrations.connections.schemas import IntegrationResourceRead
from services.integrations.connections.utils import get_visible_connection


async def list_connection_resources(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
) -> list[IntegrationResourceRead]:
    """Return live and provider-removed resources, excluding soft-deleted rows."""
    await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    resources = (
        await db.scalars(
            select(IntegrationResource)
            .where(
                IntegrationResource.connection_id == connection_id,
                IntegrationResource.deleted.is_(False),
            )
            .order_by(
                IntegrationResource.resource_type,
                IntegrationResource.display_name,
                IntegrationResource.external_id,
            )
        )
    ).all()
    return [_resource_to_read(resource) for resource in resources]


def _resource_to_read(resource: IntegrationResource) -> IntegrationResourceRead:
    return IntegrationResourceRead(
        id=resource.id,
        connection_id=resource.connection_id,
        resource_type=resource.resource_type,
        external_id=resource.external_id,
        display_name=resource.display_name,
        parent_external_id=resource.parent_external_id,
        enabled=resource.enabled,
        availability=resource.availability,
        writable=resource.writable,
        metadata=resource.permissions_metadata or {},
        first_seen_at=resource.first_seen_at,
        last_seen_at=resource.last_seen_at,
        removed_at=resource.removed_at,
    )
