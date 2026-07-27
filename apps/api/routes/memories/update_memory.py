# apps/api/routes/memories/update_memory.py

"""Update one workspace-visible memory."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.memories import edit_memory as edit_memory_service
from services.memories.schemas import MemoryResponse, MemoryUpdateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.patch("/{memory_id}")
async def update_memory(
    memory_id: Annotated[UUID, Path()],
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: MemoryUpdateRequest,
) -> MemoryResponse:
    workspace, membership = workspace_context
    return await edit_memory_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        memory_id=memory_id,
        payload=payload,
    )
