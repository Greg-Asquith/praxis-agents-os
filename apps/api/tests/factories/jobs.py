# apps/api/tests/factories/jobs.py

"""Job model factories for tests."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from models.jobs import Job
from services.jobs.domain import JOB_STATUS_PENDING
from services.jobs.utils import compute_content_hash


def build_job(
    *,
    job_id: UUID | None = None,
    kind: str = "jobs.sweep_terminal",
    workspace_id: UUID | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    payload: dict[str, object] | None = None,
    content_hash: str | None = None,
    priority: int = 100,
    status: str = JOB_STATUS_PENDING,
    run_after: datetime | None = None,
    attempts: int = 0,
    max_attempts: int = 5,
    initiated_by_user_id: UUID | None = None,
) -> Job:
    """Build an unsaved generic job model."""
    normalized_payload = payload or {}
    return Job(
        id=job_id or uuid4(),
        kind=kind,
        workspace_id=workspace_id,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=normalized_payload,
        content_hash=content_hash or compute_content_hash(normalized_payload),
        priority=priority,
        status=status,
        run_after=run_after or datetime.now(UTC),
        attempts=attempts,
        max_attempts=max_attempts,
        initiated_by_user_id=initiated_by_user_id,
    )
