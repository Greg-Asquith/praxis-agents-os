# apps/api/routes/mail_merges/pause_mail_merge.py

"""Route for pausing a mail merge before its next email."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.mail_merge import pause_mail_merge as pause_service
from services.mail_merge.schemas import MailMergeRead

router = APIRouter()


@router.post("/{merge_id}/pause")
async def pause_mail_merge(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    merge_id: Annotated[UUID, Path()],
) -> MailMergeRead:
    workspace, membership = workspace_context
    return await pause_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        merge_id=merge_id,
    )
