# apps/api/services/jobs/finalize_job.py

"""Finalize generic background job attempts."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from services.jobs.utils import retry_backoff, sanitize_error_message
from services.notifications import create_notification


async def finalize_job_success(
    db: AsyncSession,
    job: Job,
    *,
    owner_instance_id: str,
    now: datetime | None = None,
) -> bool:
    """Marks an owned job attempt as successful and terminal."""
    now_utc = now or datetime.now(UTC)
    result = await db.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == JOB_STATUS_RUNNING,
            Job.locked_by == owner_instance_id,
        )
        .values(
            status=JOB_STATUS_SUCCEEDED,
            finished_at=now_utc,
            locked_by=None,
            locked_at=None,
            lock_expires_at=None,
            last_error_code=None,
            last_error_message=None,
        )
        .returning(Job.id)
    )
    if result.scalar_one_or_none() is None:
        return False
    await db.refresh(job)
    return True


async def finalize_job_failure(
    db: AsyncSession,
    job: Job,
    *,
    owner_instance_id: str,
    code: str,
    message: str,
    now: datetime | None = None,
    force_terminal: bool = False,
) -> bool | None:
    """Records an owned failure, returning its terminal state or None after ownership loss."""
    now_utc = now or datetime.now(UTC)
    error_code = code[:64]
    error_message = sanitize_error_message(message)
    terminal = force_terminal or (job.attempts or 0) >= job.max_attempts
    values = {
        "last_error_code": error_code,
        "last_error_message": error_message,
        "locked_by": None,
        "locked_at": None,
        "lock_expires_at": None,
        "status": JOB_STATUS_FAILED if terminal else JOB_STATUS_PENDING,
        "finished_at": now_utc if terminal else None,
    }
    if not terminal:
        values["run_after"] = now_utc + timedelta(seconds=retry_backoff(job.attempts or 1))
    result = await db.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == JOB_STATUS_RUNNING,
            Job.locked_by == owner_instance_id,
        )
        .values(**values)
        .returning(Job.id)
    )
    if result.scalar_one_or_none() is None:
        return None
    await db.refresh(job)

    if terminal:
        if job.initiated_by_user_id is not None:
            await create_notification(
                db,
                notification_type="job_failed",
                title="Background job failed",
                body=error_message,
                payload={"job_id": str(job.id), "kind": job.kind, "error_code": error_code},
                recipient_user_id=str(job.initiated_by_user_id),
                workspace_id=str(job.workspace_id) if job.workspace_id else None,
                source="jobs",
            )
        await db.flush()
        return True
    return False
