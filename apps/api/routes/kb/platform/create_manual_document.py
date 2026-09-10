# apps/api/routes/kb/platform/create_manual_document.py

"""Creates manual document through super-admin platform management."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import create_manual_document as service
from services.kb.schemas import KBDocumentRead, PlatformKBManualDocumentCreateRequest

router = APIRouter()


@router.post("/")
async def create_manual_document(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: PlatformKBManualDocumentCreateRequest,
) -> KBDocumentRead:
    return await service(db, actor=actor, request=request, payload=payload)
