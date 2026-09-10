# apps/api/routes/files/platform/withdraw_file.py

"""Withdraws a platform File from publication."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileRead
from services.files.platform import withdraw_file as withdraw_file_service

router = APIRouter()


@router.post("/{file_id}/withdraw")
async def withdraw_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> FileRead:
    return await withdraw_file_service(
        db,
        actor=actor,
        file_id=file_id,
        request=request,
    )
