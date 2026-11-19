# apps/api/routes/mail_merges/get_mail_merge.py

"""Route for reading a mail merge's progress and results."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.mail_merge import get_mail_merge as get_service
from services.mail_merge.schemas import MailMergeRead

router = APIRouter()


@router.get("/{merge_id}")
async def get_mail_merge(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    merge_id: Annotated[UUID, Path()],
) -> MailMergeRead:
    workspace, membership = workspace_context
    return await get_service(
        db, actor=actor, workspace=workspace, membership=membership, merge_id=merge_id
    )
