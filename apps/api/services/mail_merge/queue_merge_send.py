# apps/api/services/mail_merge/queue_merge_send.py

"""Queue the next chunk of a merge's background sending."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from models.mail_merge import MailMerge
from services.jobs.enqueue_job import enqueue_job
from services.mail_merge.domain import MAIL_MERGE_SEND_JOB_KIND


async def queue_merge_send(
    db: AsyncSession, *, merge: MailMerge, run_after: datetime | None = None
) -> None:
    """Queues one send job for the merge; a second queue while one waits merges into it."""
    await enqueue_job(
        db,
        kind=MAIL_MERGE_SEND_JOB_KIND,
        workspace_id=merge.workspace_id,
        subject_type="mail_merge",
        subject_id=merge.id,
        payload={"merge_id": str(merge.id)},
        run_after=run_after,
        initiated_by_user_id=merge.created_by_user_id,
    )
