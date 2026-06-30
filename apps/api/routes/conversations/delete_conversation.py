# apps/api/routes/conversations/delete_conversation.py

"""Route for soft-deleting a conversation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.conversations import delete_conversation as delete_conversation_service

router = APIRouter()


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    conversation_id: Annotated[UUID, Path()],
) -> None:
    workspace, _membership = workspace_context
    await delete_conversation_service(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
