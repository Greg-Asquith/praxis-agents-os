# apps/api/routes/integrations/save_context_file.py

"""Save a provider file into Files from a conversation's tool card."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.integrations.file_sources import (
    IntegrationFileSaveRead,
    IntegrationFileSourceCreate,
    save_integration_file,
)

router = APIRouter()


@router.post("/conversations/{conversation_id}/file-saves")
async def save_context_file(
    conversation_id: Annotated[UUID, Path()],
    payload: IntegrationFileSourceCreate,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> IntegrationFileSaveRead:
    workspace, membership = workspace_context
    return await save_integration_file(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        conversation_id=conversation_id,
        payload=payload,
    )
