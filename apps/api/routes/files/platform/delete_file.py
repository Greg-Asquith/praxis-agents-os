# apps/api/routes/files/platform/delete_file.py

"""Deletes a platform File."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.platform import delete_file as delete_file_service

router = APIRouter()


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> Response:
    await delete_file_service(
        db,
        actor=actor,
        file_id=file_id,
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
