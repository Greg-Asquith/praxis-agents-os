# apps/api/services/kb/integration_sources/search.py

"""Search one authorized integration resource for Knowledge Base sources."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.integrations.plugin import KnowledgeSourceSearchResult
from services.kb.documents.utils import require_kb_write_access
from services.kb.integration_sources.authorize import authorize_integration_knowledge_source
from services.kb.integration_sources.utils import map_knowledge_source_auth_error


async def search_integration_knowledge_sources(
    db: AsyncSession,
    *,
    integration_resource_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    query: str | None,
    limit: int,
) -> tuple[KnowledgeSourceSearchResult, ...]:
    """Returns bounded source matches from one actor-owned integration resource."""
    require_kb_write_access(membership)
    authorized = await authorize_integration_knowledge_source(
        db,
        integration_resource_id=integration_resource_id,
        actor=actor,
        workspace=workspace,
    )
    await db.commit()
    try:
        results = await authorized.definition.search(
            db,
            authorized.connection,
            authorized.resource,
            query,
            limit,
        )
    except IntegrationAuthError as exc:
        raise map_knowledge_source_auth_error(exc) from exc
    return tuple(results)
