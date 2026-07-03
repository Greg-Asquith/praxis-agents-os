# apps/api/routes/skills/list_documents.py

"""Route for listing skill documents."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.skills.documents import list_skill_documents as list_documents_service
from services.skills.documents.domain import SkillDocumentsListResponse

router = APIRouter()


@router.get("/{skill_id}/documents")
async def list_skill_documents(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
) -> SkillDocumentsListResponse:
    workspace, _membership = workspace_context
    return await list_documents_service(db, workspace=workspace, skill_id=skill_id)
