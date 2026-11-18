# apps/api/services/mail_merge/stop_user_mail_merges.py

"""Stop every merge that sends as a user who can no longer act."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import tenant_context
from models.mail_merge import MailMerge
from models.user import User
from models.workspace import WorkspaceMembership
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)
from services.mail_merge.domain import (
    MERGE_STATUS_PAUSED,
    MERGE_STATUS_QUEUED,
    MERGE_STATUS_SENDING,
    MERGE_STATUS_STOPPED,
    STOP_REASON_SENDER_REMOVED,
)


async def stop_user_mail_merges(
    db: AsyncSession, *, request: Request, actor: User, user_id: UUID, reason: str
) -> int:
    """Stops the user's unfinished merges in each workspace they joined, returning the count.

    Unsent rows stay unsent, and a stopped merge can't be resumed. The send job also checks
    the sender's membership before each email, which covers leaving one workspace.
    """
    # Merges are under workspace RLS, so switch tenant context per workspace.
    workspace_ids = (
        await db.scalars(
            select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user_id)
        )
    ).all()
    stopped = 0
    for workspace_id in workspace_ids:
        async with tenant_context(db, workspace_id=workspace_id, user_id=actor.id):
            merge_ids = (
                await db.scalars(
                    update(MailMerge)
                    .where(
                        MailMerge.workspace_id == workspace_id,
                        MailMerge.created_by_user_id == user_id,
                        MailMerge.status.in_(
                            (MERGE_STATUS_QUEUED, MERGE_STATUS_SENDING, MERGE_STATUS_PAUSED)
                        ),
                    )
                    .values(
                        status=MERGE_STATUS_STOPPED,
                        stop_reason=STOP_REASON_SENDER_REMOVED,
                        finished_at=datetime.now(UTC),
                    )
                    .returning(MailMerge.id)
                )
            ).all()
            for merge_id in merge_ids:
                await safe_record_operation_audit_event(
                    db,
                    workspace_id=workspace_id,
                    action=AuditAction.CANCEL,
                    resource_type=AuditResourceType.MAIL_MERGE,
                    resource_id=merge_id,
                    actor_type=AuditActorType.USER,
                    actor_id=actor.id,
                    actor_display=actor.email,
                    requested_by_user_id=actor.id,
                    details={"reason": reason, "sender_user_id": str(user_id)},
                    request=request,
                )
        stopped += len(merge_ids)
    return stopped
