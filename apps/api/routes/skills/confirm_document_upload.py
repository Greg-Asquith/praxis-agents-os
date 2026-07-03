# apps/api/routes/skills/confirm_document_upload.py

"""Route for confirming skill document uploads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.skills.documents import confirm_skill_document_upload as confirm_service
from services.skills.documents.domain import SkillDocumentConfirmRequest, SkillDocumentRead

router = APIRouter()


@router.post("/{skill_id}/documents/confirm")
async def confirm_skill_document_upload(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
    payload: SkillDocumentConfirmRequest,
) -> SkillDocumentRead:
    workspace, membership = workspace_context
    return await confirm_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        skill_id=skill_id,
        payload=payload,
    )
