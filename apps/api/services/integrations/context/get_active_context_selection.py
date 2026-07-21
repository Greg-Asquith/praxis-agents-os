# apps/api/services/integrations/context/get_active_context_selection.py

"""Read one conversation's active integration context selection."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integration_context import ActiveContextSelection
from models.user import User
from models.workspace import Workspace
from services.conversations.utils import get_conversation_for_actor


async def get_active_context_selection(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> ActiveContextSelection | None:
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    return await db.scalar(
        select(ActiveContextSelection)
        .where(
            ActiveContextSelection.conversation_id == conversation.id,
            ActiveContextSelection.workspace_id == workspace.id,
        )
        .execution_options(populate_existing=True)
    )
