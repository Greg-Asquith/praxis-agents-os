# apps/api/routes/conversations/update_sharing.py

"""Route for changing a chat's workspace audience."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, require_read
from models.workspace import Workspace, WorkspaceMembership
from services.conversation_read_contract import ConversationRead, SharedConversationRead
from services.conversations.schemas import ConversationSharingRequest
from services.conversations.update_sharing import update_conversation_sharing

router = APIRouter()


@router.put("/{conversation_id}/sharing")
async def update_sharing(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: Annotated[tuple[Workspace, WorkspaceMembership], Depends(require_read)],
    conversation_id: Annotated[UUID, Path()],
    payload: ConversationSharingRequest,
) -> ConversationRead | SharedConversationRead:
    workspace, _membership = workspace_context
    return await update_conversation_sharing(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        visibility=payload.visibility,
        request=request,
    )
