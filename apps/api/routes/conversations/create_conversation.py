# apps/api/routes/conversations/create_conversation.py

"""Route for creating a conversation and streaming its first turn."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import create_conversation_stream
from services.conversations.schemas import ConversationCreateRequest

router = APIRouter()


@router.post("/")
async def create_conversation(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    request: Request,
    payload: ConversationCreateRequest,
) -> StreamingResponse:
    workspace, _membership = workspace_context
    return await create_conversation_stream(
        db,
        actor=actor,
        workspace=workspace,
        payload=payload,
        request=request,
    )
