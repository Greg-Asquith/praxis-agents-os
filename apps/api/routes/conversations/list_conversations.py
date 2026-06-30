# apps/api/routes/conversations/list_conversations.py

"""Route for listing conversations."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import list_conversations as list_conversations_service
from services.conversations.schemas import ConversationsListResponse

router = APIRouter()


@router.get("/")
async def list_conversations(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationsListResponse:
    workspace, _membership = workspace_context
    return await list_conversations_service(
        db,
        actor=actor,
        workspace=workspace,
        limit=limit,
        offset=offset,
    )
