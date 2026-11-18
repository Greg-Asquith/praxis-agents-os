# apps/api/services/jobs/handlers/send_mail_merge.py

"""Sends a mail merge in the background, one chunk per job."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.registry import job_handler
from services.mail_merge import send_merge_chunk, stop_merge_after_job_failure
from services.mail_merge.domain import MAIL_MERGE_SEND_JOB_KIND
from services.mail_merge.send_merge_chunk import CHUNK_MAX_SECONDS

# Room for the last send of a chunk and the final commit.
JOB_ALLOWANCE_SECONDS = 120


@job_handler(
    kind=MAIL_MERGE_SEND_JOB_KIND,
    timeout=CHUNK_MAX_SECONDS + JOB_ALLOWANCE_SECONDS,
    max_attempts=3,
    on_final_failure=stop_merge_after_job_failure,
)
async def send_mail_merge(db: AsyncSession, job: Job) -> None:
    """Safe to run twice: rows caught mid-send are reconciled from stored draft IDs first."""
    await send_merge_chunk(db, job)
