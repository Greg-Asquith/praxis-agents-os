# apps/api/routes/conversations/list_messages.py

"""Route for listing conversation messages."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import list_conversation_messages
from services.conversations.schemas import ConversationMessagesResponse

router = APIRouter()


@router.get("/{conversation_id}/messages")
async def list_messages(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    conversation_id: Annotated[UUID, Path()],
) -> ConversationMessagesResponse:
    workspace, _membership = workspace_context
    return await list_conversation_messages(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
