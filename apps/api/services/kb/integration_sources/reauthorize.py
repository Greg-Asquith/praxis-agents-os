# apps/api/services/kb/integration_sources/reauthorize.py

"""Reauthorize a Knowledge Base integration import after provider I/O."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import NotFoundError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.kb.documents.utils import require_kb_write_access
from services.kb.integration_sources.authorize import authorize_integration_knowledge_source
from services.kb.integration_sources.domain import AuthorizedIntegrationKnowledgeSource


async def reauthorize_integration_knowledge_source(
    db: AsyncSession,
    *,
    integration_resource_id: UUID,
    membership_id: UUID,
    actor: User,
    workspace: Workspace,
) -> AuthorizedIntegrationKnowledgeSource:
    """Returns a fresh usable source after confirming current workspace access."""
    current_workspace = await db.get(Workspace, workspace.id, populate_existing=True)
    if current_workspace is None or current_workspace.deleted:
        raise NotFoundError(
            "Integration resource not found",
            resource_type="integration_resource",
            resource_id=str(integration_resource_id),
        )
    membership = await db.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.id == membership_id,
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == actor.id,
            WorkspaceMembership.deleted.is_(False),
        )
        .execution_options(populate_existing=True)
    )
    if membership is None:
        raise AuthorizationError("Requires workspace write access")
    require_kb_write_access(membership)
    return await authorize_integration_knowledge_source(
        db,
        integration_resource_id=integration_resource_id,
        actor=actor,
        workspace=workspace,
    )
