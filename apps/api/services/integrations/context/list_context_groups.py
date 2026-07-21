# apps/api/services/integrations/context/list_context_groups.py

"""List active context groups in a workspace."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.integration_context import IntegrationContextGroup, IntegrationContextGroupMember
from models.workspace import Workspace
from services.integrations.context.schemas import ContextGroupListResponse, ContextGroupRead


async def list_context_groups(
    db: AsyncSession,
    *,
    workspace: Workspace,
) -> ContextGroupListResponse:
    groups = (
        await db.scalars(
            select(IntegrationContextGroup)
            .options(
                selectinload(IntegrationContextGroup.members).selectinload(
                    IntegrationContextGroupMember.resource
                )
            )
            .where(
                IntegrationContextGroup.workspace_id == workspace.id,
                IntegrationContextGroup.deleted.is_(False),
            )
            .order_by(func.lower(IntegrationContextGroup.name), IntegrationContextGroup.id)
        )
    ).all()
    return ContextGroupListResponse(items=[ContextGroupRead.from_group(group) for group in groups])
