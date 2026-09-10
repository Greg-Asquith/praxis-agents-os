# apps/api/routes/kb/platform/withdraw_document.py

"""Withdraws document through super-admin platform management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import withdraw_document as service
from services.kb.schemas import KBDocumentRead

router = APIRouter()


@router.post("/{document_id}/withdraw")
async def withdraw_document(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    document_id: Annotated[UUID, Path()],
) -> KBDocumentRead:
    return await service(db, actor=actor, request=request, document_id=document_id)
