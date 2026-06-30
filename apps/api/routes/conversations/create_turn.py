# apps/api/routes/conversations/create_turn.py

"""Route for starting a streamed conversation turn."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path
from fastapi.responses import StreamingResponse

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import create_conversation_turn_stream
from services.conversations.schemas import ConversationTurnCreateRequest

router = APIRouter()


@router.post("/{conversation_id}/turns")
async def create_turn(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    conversation_id: Annotated[UUID, Path()],
    payload: ConversationTurnCreateRequest,
) -> StreamingResponse:
    workspace, _membership = workspace_context
    return await create_conversation_turn_stream(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        payload=payload,
    )
