# apps/api/services/jobs/finalize_job.py

"""Finalize generic background job attempts."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import (
    JOB_STATUS_FAILED,
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
)
from services.jobs.registry import get_job_handler
from services.jobs.utils import (
    is_pending_job_duplicate_error,
    retry_backoff,
    sanitize_error_message,
)
from services.notifications import create_notification

logger = logging.getLogger(__name__)

SUPERSEDED_ERROR_CODE = "superseded"


async def finalize_job_success(
    db: AsyncSession,
    job: Job,
    *,
    lease_token: UUID,
    now: datetime | None = None,
) -> bool:
    """Marks the job successful when the caller still holds the running attempt."""
    return await _update_running_attempt(
        db,
        job,
        lease_token=lease_token,
        status=JOB_STATUS_SUCCEEDED,
        finished_at=now or datetime.now(UTC),
        locked_by=None,
        locked_at=None,
        lock_expires_at=None,
        last_error_code=None,
        last_error_message=None,
    )


async def finalize_job_failure(
    db: AsyncSession,
    job: Job,
    *,
    lease_token: UUID,
    code: str,
    message: str,
    now: datetime | None = None,
    force_terminal: bool = False,
) -> bool | None:
    """Records the attempt's failure, returning its terminal state or None after lease loss."""
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
    try:
        async with db.begin_nested():
            finalized = await _update_running_attempt(db, job, lease_token=lease_token, **values)
    except IntegrityError as exc:
        if not is_pending_job_duplicate_error(exc):
            raise
        # A pending follow-up repeats this work, so the attempt closes instead of retrying.
        superseded = await _update_running_attempt(
            db,
            job,
            lease_token=lease_token,
            **{
                **values,
                "status": JOB_STATUS_FAILED,
                "finished_at": now_utc,
                "last_error_code": SUPERSEDED_ERROR_CODE,
            },
        )
        return True if superseded else None
    if not finalized:
        return None

    if terminal:
        await _run_final_failure_hook(db, job)
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


async def _update_running_attempt(
    db: AsyncSession, job: Job, *, lease_token: UUID, **values: object
) -> bool:
    result = await db.execute(
        update(Job)
        .where(
            Job.id == job.id,
            Job.status == JOB_STATUS_RUNNING,
            Job.lease_token == lease_token,
        )
        .values(**values)
        .returning(Job.id)
    )
    if result.scalar_one_or_none() is None:
        return False
    await db.refresh(job)
    return True


async def _run_final_failure_hook(db: AsyncSession, job: Job) -> None:
    definition = get_job_handler(job.kind)
    if definition is None or definition.on_final_failure is None:
        return
    try:
        async with db.begin_nested():
            await definition.on_final_failure(db, job)
    except Exception:
        logger.exception(
            "Final failure hook failed", extra={"job_id": str(job.id), "kind": job.kind}
        )
