# apps/api/services/kb/integration_sources/authorize.py

"""Authorize a personal integration resource for Knowledge Base import."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.user import User
from models.workspace import Workspace
from services.kb.integration_sources.domain import AuthorizedIntegrationKnowledgeSource
from services.kb.integration_sources.utils import load_personal_knowledge_source


async def authorize_integration_knowledge_source(
    db: AsyncSession,
    *,
    integration_resource_id: UUID,
    actor: User,
    workspace: Workspace,
) -> AuthorizedIntegrationKnowledgeSource:
    """Returns one usable personal source without revealing hidden resources."""
    if workspace.deleted:
        raise _not_found(integration_resource_id)
    return await load_personal_knowledge_source(
        db,
        resource_id=integration_resource_id,
        owner_user_id=actor.id,
        unavailable_error=lambda _provider_key: _not_found(integration_resource_id),
    )


def _not_found(integration_resource_id: UUID) -> NotFoundError:
    return NotFoundError(
        "Integration resource not found",
        resource_type="integration_resource",
        resource_id=str(integration_resource_id),
    )
