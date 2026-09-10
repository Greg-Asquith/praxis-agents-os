# apps/api/routes/kb/platform/create_document_from_file.py

"""Creates document from file through super-admin platform management."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import create_document_from_file as service
from services.kb.schemas import KBDocumentRead, PlatformKBFileDocumentCreateRequest

router = APIRouter()


@router.post("/from-file")
async def create_document_from_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: PlatformKBFileDocumentCreateRequest,
) -> KBDocumentRead:
    return await service(db, actor=actor, request=request, payload=payload)
