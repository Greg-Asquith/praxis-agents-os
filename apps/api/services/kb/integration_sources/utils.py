# apps/api/services/kb/integration_sources/utils.py

"""Shared integration-source lookup helpers."""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection, IntegrationResource
from services.integrations.domain import CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS
from services.integrations.plugin import PROVIDER_PLUGINS
from services.kb.integration_sources.domain import AuthorizedIntegrationKnowledgeSource

UnavailableErrorFactory = Callable[[str | None], Exception]


async def load_personal_knowledge_source(
    db: AsyncSession,
    *,
    resource_id: UUID,
    owner_user_id: UUID,
    unavailable_error: UnavailableErrorFactory,
) -> AuthorizedIntegrationKnowledgeSource:
    """Load one usable personal resource and its provider source contribution."""
    row = (
        await db.execute(
            select(IntegrationResource, IntegrationConnection)
            .join(
                IntegrationConnection,
                IntegrationConnection.id == IntegrationResource.connection_id,
            )
            .where(
                IntegrationResource.id == resource_id,
                IntegrationResource.deleted.is_(False),
                IntegrationResource.availability == "available",
                IntegrationConnection.deleted.is_(False),
                IntegrationConnection.owner_user_id == owner_user_id,
                IntegrationConnection.owner_workspace_id.is_(None),
                IntegrationConnection.status.not_in(CONNECTION_STATUSES_WITHOUT_USABLE_CREDENTIALS),
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise unavailable_error(None)

    resource, connection = row
    plugin = PROVIDER_PLUGINS.get(connection.provider_key)
    definition = plugin.knowledge_source if plugin is not None else None
    if definition is None or resource.resource_type not in definition.resource_types:
        raise unavailable_error(connection.provider_key)
    return AuthorizedIntegrationKnowledgeSource(
        connection=connection,
        resource=resource,
        definition=definition,
    )
