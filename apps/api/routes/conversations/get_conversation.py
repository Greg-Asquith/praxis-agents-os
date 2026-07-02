# apps/api/routes/conversations/get_conversation.py

"""Route for reading a conversation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import get_conversation as get_conversation_service
from services.conversations.schemas import ConversationRead

router = APIRouter()


@router.get("/{conversation_id}")
async def get_conversation(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    conversation_id: Annotated[UUID, Path()],
) -> ConversationRead:
    workspace, _membership = workspace_context
    return await get_conversation_service(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
