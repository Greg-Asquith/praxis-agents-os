# apps/api/routes/kb/platform/publish_document.py

"""Publishes document through super-admin platform management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.kb.platform import publish_document as service
from services.kb.schemas import KBDocumentRead, PlatformKBDocumentPublishRequest

router = APIRouter()


@router.post("/{document_id}/publish")
async def publish_document(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    document_id: Annotated[UUID, Path()],
    payload: PlatformKBDocumentPublishRequest,
) -> KBDocumentRead:
    return await service(db, actor=actor, request=request, document_id=document_id, payload=payload)
