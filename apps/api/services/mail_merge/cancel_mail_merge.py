# apps/api/services/mail_merge/cancel_mail_merge.py

"""Cancel a merge for good. Emails already sent stay sent, and no more go out."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.mail_merge.domain import MERGE_STATUS_CANCELLED
from services.mail_merge.get_mail_merge import mail_merge_read
from services.mail_merge.schemas import MailMergeRead
from services.mail_merge.utils import get_merge_for_actor, move_merge


async def cancel_mail_merge(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    merge_id: UUID,
) -> MailMergeRead:
    """Cancels an unfinished merge; its unsent rows are never sent.

    Raises:
        ConflictError: Thrown when the merge has already finished.
    """
    merge = await get_merge_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        merge_id=merge_id,
        for_update=True,
    )
    move_merge(merge, MERGE_STATUS_CANCELLED, now=datetime.now(UTC))
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CANCEL,
        resource_type=AuditResourceType.MAIL_MERGE,
        resource_id=merge.id,
        actor=actor,
        details={"status": MERGE_STATUS_CANCELLED},
    )
    return await mail_merge_read(db, merge)
