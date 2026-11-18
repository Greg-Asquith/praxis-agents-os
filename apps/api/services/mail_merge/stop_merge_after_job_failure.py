# apps/api/services/mail_merge/stop_merge_after_job_failure.py

"""Stop a merge whose send job failed for good."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from models.mail_merge import MailMerge, MailMergeRecipient
from services.mail_merge.domain import (
    MERGE_STATUS_PAUSED,
    MERGE_STATUS_QUEUED,
    MERGE_STATUS_SENDING,
    MERGE_STATUS_STOPPED,
    RECIPIENT_STATUS_SENDING,
    RECIPIENT_STATUS_UNVERIFIED,
    STOP_REASON_SEND_FAILED,
)
from services.mail_merge.utils import move_merge


async def stop_merge_after_job_failure(db: AsyncSession, job: Job) -> None:
    """Stops the merge, and marks rows caught mid-send Couldn't Confirm.

    A stopped merge never sends again, so nothing would reconcile those rows later, and
    they are never resent.
    """
    try:
        merge_id = UUID(str((job.payload or {}).get("merge_id")))
    except ValueError:
        return
    merge = await db.scalar(
        select(MailMerge)
        .where(MailMerge.id == merge_id, MailMerge.workspace_id == job.workspace_id)
        .with_for_update()
    )
    if merge is None or merge.status not in (
        MERGE_STATUS_QUEUED,
        MERGE_STATUS_SENDING,
        MERGE_STATUS_PAUSED,
    ):
        return
    move_merge(
        merge, MERGE_STATUS_STOPPED, now=datetime.now(UTC), stop_reason=STOP_REASON_SEND_FAILED
    )
    await db.execute(
        update(MailMergeRecipient)
        .where(
            MailMergeRecipient.merge_id == merge.id,
            MailMergeRecipient.status == RECIPIENT_STATUS_SENDING,
        )
        .values(status=RECIPIENT_STATUS_UNVERIFIED)
    )
