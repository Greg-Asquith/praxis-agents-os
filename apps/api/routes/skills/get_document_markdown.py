# apps/api/routes/skills/get_document_markdown.py

"""Route for reading converted skill document markdown."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.skills.documents import get_skill_document_markdown as get_markdown_service
from services.skills.documents.domain import (
    SKILL_DOC_NAME_PATTERN,
    SkillDocumentMarkdownResponse,
)

router = APIRouter()


@router.get("/{skill_id}/documents/{document_name}/markdown")
async def get_skill_document_markdown(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
    document_name: Annotated[str, Path(min_length=1, max_length=64, pattern=SKILL_DOC_NAME_PATTERN)],
) -> SkillDocumentMarkdownResponse:
    workspace, _membership = workspace_context
    return await get_markdown_service(
        db,
        workspace=workspace,
        skill_id=skill_id,
        document_name=document_name,
    )
