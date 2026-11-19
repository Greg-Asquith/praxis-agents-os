# apps/api/routes/mail_merges/cancel_mail_merge.py

"""Route for cancelling a mail merge."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.mail_merge import cancel_mail_merge as cancel_service
from services.mail_merge.schemas import MailMergeRead

router = APIRouter()


@router.post("/{merge_id}/cancel")
async def cancel_mail_merge(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    merge_id: Annotated[UUID, Path()],
) -> MailMergeRead:
    workspace, membership = workspace_context
    return await cancel_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        merge_id=merge_id,
    )
