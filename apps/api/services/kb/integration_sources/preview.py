# apps/api/services/kb/integration_sources/preview.py

"""Preview one authorized integration source for Knowledge Base import."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.integrations.plugin import KnowledgeSourcePreview
from services.kb.documents.utils import require_kb_write_access
from services.kb.integration_sources.authorize import authorize_integration_knowledge_source
from services.kb.integration_sources.utils import map_knowledge_source_auth_error


async def preview_integration_knowledge_source(
    db: AsyncSession,
    *,
    integration_resource_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    source: str | dict[str, object],
) -> KnowledgeSourcePreview:
    """Returns a bounded preview from one actor-owned integration resource."""
    require_kb_write_access(membership)
    authorized = await authorize_integration_knowledge_source(
        db,
        integration_resource_id=integration_resource_id,
        actor=actor,
        workspace=workspace,
    )
    normalized_reference = authorized.definition.parse_source(source)
    await db.commit()
    try:
        return await authorized.definition.preview(
            db,
            authorized.connection,
            authorized.resource,
            normalized_reference,
        )
    except IntegrationAuthError as exc:
        raise map_knowledge_source_auth_error(exc) from exc
