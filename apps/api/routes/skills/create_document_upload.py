# apps/api/routes/skills/create_document_upload.py

"""Route for creating skill document upload grants."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.assets.domain import AssetUploadGrant
from services.skills.documents import create_skill_document_upload as create_upload_service
from services.skills.documents.domain import SkillDocumentUploadRequest

router = APIRouter()


@router.post("/{skill_id}/documents/upload")
async def create_skill_document_upload(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
    payload: SkillDocumentUploadRequest,
) -> AssetUploadGrant:
    workspace, membership = workspace_context
    return await create_upload_service(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        skill_id=skill_id,
        payload=payload,
    )
