# apps/api/routes/memories/delete_memory.py

"""Archive or explicitly purge one workspace-visible memory."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from core.dependencies import (
    AsyncDbSessionDep,
    CurrentUserDep,
    CurrentWorkspaceDep,
    require_editor,
)
from services.memories import remove_memory as remove_memory_service

router = APIRouter(dependencies=[Depends(require_editor)])


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: Annotated[UUID, Path()],
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    purge: Annotated[bool, Query()] = False,
) -> Response:
    workspace, membership = workspace_context
    await remove_memory_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        memory_id=memory_id,
        purge=purge,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
