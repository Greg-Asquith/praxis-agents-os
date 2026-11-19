# apps/api/services/mail_merge/get_mail_merge.py

"""Read a merge's progress and every recipient's outcome, for its card in the conversation."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationConnection
from models.mail_merge import MailMerge, MailMergeRecipient
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.mail_merge.budget import estimate_merge_finish, get_send_budget
from services.mail_merge.domain import (
    FINAL_MERGE_STATUSES,
    MERGE_STATUS_PAUSED,
    RECIPIENT_STATUS_FAILED,
    RECIPIENT_STATUS_SENDING,
    RECIPIENT_STATUS_SENT,
    RECIPIENT_STATUS_SKIPPED,
    RECIPIENT_STATUS_UNVERIFIED,
    STOP_REASON_DAILY_LIMIT,
)
from services.mail_merge.schemas import (
    MailMergeCounts,
    MailMergeRead,
    MailMergeRecipientRead,
    MailMergeRowState,
)
from services.mail_merge.utils import connection_account_kind, get_merge_for_actor

_ROW_STATES: dict[str, MailMergeRowState] = {
    RECIPIENT_STATUS_SENT: "sent",
    RECIPIENT_STATUS_FAILED: "failed",
    RECIPIENT_STATUS_UNVERIFIED: "unverified",
    RECIPIENT_STATUS_SKIPPED: "skipped",
}


async def get_mail_merge(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    merge_id: UUID,
) -> MailMergeRead:
    merge = await get_merge_for_actor(
        db, actor=actor, workspace=workspace, membership=membership, merge_id=merge_id
    )
    return await mail_merge_read(db, merge)


async def mail_merge_read(db: AsyncSession, merge: MailMerge) -> MailMergeRead:
    """Builds the merge's progress from its rows, with timing from the mailbox's budget."""
    rows = (
        await db.scalars(
            select(MailMergeRecipient)
            .where(MailMergeRecipient.merge_id == merge.id)
            .order_by(MailMergeRecipient.position)
        )
    ).all()
    finished = merge.status in FINAL_MERGE_STATUSES
    recipients = [_recipient_read(row, finished=finished) for row in rows]
    counts = MailMergeCounts(
        total=len(recipients),
        **{
            state: sum(1 for row in recipients if row.state == state)
            for state in ("waiting", "sent", "failed", "unverified", "skipped")
        },
    )
    estimated_finish, resumes_at = await _timing(db, merge, waiting=counts.waiting)
    return MailMergeRead(
        id=merge.id,
        provider_key=merge.provider_key,
        sender_address=merge.sender_address,
        status=merge.status,
        stop_reason=merge.stop_reason,
        created_at=merge.created_at,
        finished_at=merge.finished_at,
        estimated_finish=estimated_finish,
        resumes_at=resumes_at,
        counts=counts,
        recipients=recipients,
    )


def _recipient_read(row: MailMergeRecipient, *, finished: bool) -> MailMergeRecipientRead:
    # A send still in flight when the merge ended has no confirmed outcome.
    if finished and row.status == RECIPIENT_STATUS_SENDING:
        state: MailMergeRowState = "unverified"
    else:
        state = _ROW_STATES.get(row.status, "waiting")
    return MailMergeRecipientRead(
        position=row.position,
        email=row.email,
        state=state,
        reason=row.error_code if state in ("failed", "skipped") else None,
        sent_at=row.sent_at,
    )


async def _timing(
    db: AsyncSession, merge: MailMerge, *, waiting: int
) -> tuple[datetime | None, datetime | None]:
    """Returns the estimated finish while the merge runs, and when a daily-limit pause clears."""
    if merge.status in FINAL_MERGE_STATUSES or waiting == 0 or merge.connection_id is None:
        return None, None
    connection = await db.get(IntegrationConnection, merge.connection_id)
    now = datetime.now(UTC)
    budget = await get_send_budget(
        db,
        connection_id=merge.connection_id,
        kind=connection_account_kind(
            connection, provider_key=merge.provider_key, sender_address=merge.sender_address
        ),
        now=now,
    )
    if merge.status == MERGE_STATUS_PAUSED:
        daily_limit = merge.stop_reason == STOP_REASON_DAILY_LIMIT
        return None, budget.frees_at if daily_limit else None
    return estimate_merge_finish(count=waiting, budget=budget, now=now), None
