# apps/api/routes/skills/create_document_download.py

"""Route for creating skill document download grants."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.skills.documents import create_skill_document_download as download_service
from services.skills.documents.domain import SKILL_DOC_NAME_PATTERN
from services.storage.domain import SignedDownload

router = APIRouter()


@router.get("/{skill_id}/documents/{document_name}/download")
async def create_skill_document_download(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
    document_name: Annotated[
        str, Path(min_length=1, max_length=64, pattern=SKILL_DOC_NAME_PATTERN)
    ],
) -> SignedDownload:
    workspace, _membership = workspace_context
    return await download_service(
        db,
        workspace=workspace,
        skill_id=skill_id,
        document_name=document_name,
    )
