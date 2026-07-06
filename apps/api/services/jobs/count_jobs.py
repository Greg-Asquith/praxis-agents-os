# apps/api/services/jobs/count_jobs.py

"""Count in-flight generic background jobs."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES


async def count_in_flight_jobs(
    db: AsyncSession,
    *,
    workspace_id: UUID | None = None,
    kind: str | None = None,
) -> dict[UUID | None, int]:
    """Return pending/running job counts by workspace.

    This is the jobs quota counter used by status surfaces and the job claim
    workspace cap.
    """
    stmt = select(Job.workspace_id, func.count(Job.id)).where(
        Job.status.in_(IN_FLIGHT_JOB_STATUSES),
    )
    if workspace_id is not None:
        stmt = stmt.where(Job.workspace_id == workspace_id)
    if kind is not None:
        stmt = stmt.where(Job.kind == kind)
    stmt = stmt.group_by(Job.workspace_id)
    rows = await db.execute(stmt)
    return {row[0]: int(row[1]) for row in rows.all()}
