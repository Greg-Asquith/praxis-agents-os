# apps/api/routes/kb/platform/delete_document.py

"""Deletes document through super-admin platform management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import delete_document as service

router = APIRouter()


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    document_id: Annotated[UUID, Path()],
) -> Response:
    await service(db, actor=actor, request=request, document_id=document_id)
    return Response(status_code=204)
