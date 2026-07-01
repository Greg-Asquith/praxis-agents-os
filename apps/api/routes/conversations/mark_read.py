# apps/api/routes/conversations/mark_read.py

"""Route for marking a conversation read."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import mark_conversation_read as mark_conversation_read_service
from services.conversations.schemas import ConversationRead

router = APIRouter()


@router.post("/{conversation_id}/read")
async def mark_conversation_read(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    conversation_id: Annotated[UUID, Path()],
) -> ConversationRead:
    workspace, _membership = workspace_context
    return await mark_conversation_read_service(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
