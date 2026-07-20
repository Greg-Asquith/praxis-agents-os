"""Derive resource-selection connection states from persisted discovery data.

This is the only service that promotes a connection to active or assigns
needs_resource_selection from integration resource state.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection, IntegrationDiscoveryRun, IntegrationResource
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.domain import (
    CONNECTION_STATUS_ACTIVE,
    CONNECTION_STATUS_DISCOVERY_PENDING,
    CONNECTION_STATUS_NEEDS_RESOURCE_SELECTION,
)
from services.integrations.manifest import PROVIDER_MANIFESTS


async def recompute_connection_status(
    db: AsyncSession,
    connection: IntegrationConnection,
) -> str:
    """Recompute selection-driven status after successful discovery or selection."""
    if connection.status not in {
        CONNECTION_STATUS_DISCOVERY_PENDING,
        CONNECTION_STATUS_NEEDS_RESOURCE_SELECTION,
        CONNECTION_STATUS_ACTIVE,
    }:
        return connection.status
    manifest = PROVIDER_MANIFESTS.get(connection.provider_key)
    if manifest is None:
        return connection.status
    if not manifest.requires_discovery:
        await transition_connection_status(db, connection, CONNECTION_STATUS_ACTIVE)
        return connection.status

    latest_status = await db.scalar(
        select(IntegrationDiscoveryRun.status)
        .where(IntegrationDiscoveryRun.connection_id == connection.id)
        .order_by(IntegrationDiscoveryRun.started_at.desc(), IntegrationDiscoveryRun.id.desc())
        .limit(1)
    )
    if latest_status != "succeeded":
        return connection.status
    enabled_count = await db.scalar(
        select(func.count())
        .select_from(IntegrationResource)
        .where(
            IntegrationResource.connection_id == connection.id,
            IntegrationResource.deleted.is_(False),
            IntegrationResource.availability != "removed",
            IntegrationResource.enabled.is_(True),
        )
    )
    target = (
        CONNECTION_STATUS_ACTIVE
        if (enabled_count or 0) >= 1
        else CONNECTION_STATUS_NEEDS_RESOURCE_SELECTION
    )
    await transition_connection_status(db, connection, target)
    return connection.status
