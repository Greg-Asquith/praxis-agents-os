# apps/api/routes/memories/get_memory.py

"""Read one workspace-visible memory."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.memories import get_memory_detail as get_memory_detail_service
from services.memories.schemas import MemoryDetailResponse

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/{memory_id}")
async def get_memory(
    memory_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> MemoryDetailResponse:
    workspace, _membership = workspace_context
    return await get_memory_detail_service(
        db,
        actor=actor,
        workspace=workspace,
        memory_id=memory_id,
    )
