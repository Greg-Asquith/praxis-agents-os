# apps/api/routes/skills/delete_document.py

"""Route for deleting skill documents."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.skills.documents import delete_skill_document as delete_document_service
from services.skills.documents.domain import SKILL_DOC_NAME_PATTERN

router = APIRouter()


@router.delete(
    "/{skill_id}/documents/{document_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_skill_document(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    skill_id: Annotated[UUID, Path()],
    document_name: Annotated[
        str, Path(min_length=1, max_length=64, pattern=SKILL_DOC_NAME_PATTERN)
    ],
) -> None:
    workspace, membership = workspace_context
    await delete_document_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        skill_id=skill_id,
        document_name=document_name,
    )
    response.status_code = status.HTTP_204_NO_CONTENT
