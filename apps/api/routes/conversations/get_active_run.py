# apps/api/routes/conversations/get_active_run.py

"""Route for reading a conversation's active run."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import get_conversation_active_run
from services.conversations.schemas import ConversationActiveRunResponse

router = APIRouter()


@router.get("/{conversation_id}/active-run")
async def get_active_run(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    conversation_id: Annotated[UUID, Path()],
) -> ConversationActiveRunResponse:
    workspace, _membership = workspace_context
    return await get_conversation_active_run(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
