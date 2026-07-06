# apps/api/services/jobs/finalize_job.py

"""Finalize generic background job attempts."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import JOB_STATUS_FAILED, JOB_STATUS_PENDING, JOB_STATUS_SUCCEEDED
from services.jobs.utils import retry_backoff, sanitize_error_message
from services.notifications.service import create_notification


async def finalize_job_success(
    db: AsyncSession,
    job: Job,
    *,
    now: datetime | None = None,
) -> None:
    """Mark a job attempt as successful and terminal."""
    now_utc = now or datetime.now(UTC)
    job.status = JOB_STATUS_SUCCEEDED
    job.finished_at = now_utc
    job.locked_by = None
    job.locked_at = None
    job.lock_expires_at = None
    job.last_error_code = None
    job.last_error_message = None
    await db.flush()


async def finalize_job_failure(
    db: AsyncSession,
    job: Job,
    *,
    code: str,
    message: str,
    now: datetime | None = None,
    force_terminal: bool = False,
) -> bool:
    """Record a failed attempt, returning True when the job is terminal."""
    now_utc = now or datetime.now(UTC)
    job.last_error_code = code[:64]
    job.last_error_message = sanitize_error_message(message)
    job.locked_by = None
    job.locked_at = None
    job.lock_expires_at = None

    if force_terminal or (job.attempts or 0) >= job.max_attempts:
        job.status = JOB_STATUS_FAILED
        job.finished_at = now_utc
        if job.initiated_by_user_id is not None:
            await create_notification(
                db,
                notification_type="job_failed",
                title="Background job failed",
                body=job.last_error_message,
                payload={"job_id": str(job.id), "kind": job.kind, "error_code": code[:64]},
                recipient_user_id=str(job.initiated_by_user_id),
                workspace_id=str(job.workspace_id) if job.workspace_id else None,
                source="jobs",
            )
        await db.flush()
        return True

    job.status = JOB_STATUS_PENDING
    job.finished_at = None
    job.run_after = now_utc + timedelta(seconds=retry_backoff(job.attempts or 1))
    await db.flush()
    return False
