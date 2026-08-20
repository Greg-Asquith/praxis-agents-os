# apps/api/services/jobs/log_concurrency_warnings.py

"""Log generic job concurrency diagnostics."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.jobs.count_jobs import count_in_flight_jobs

logger = logging.getLogger(__name__)


async def log_job_concurrency_warnings(db: AsyncSession) -> None:
    """Logs workspaces whose in-flight job count exceeds the configured limit."""
    counts = await count_in_flight_jobs(db)
    limit = settings.JOBS_WORKSPACE_CONCURRENCY_LIMIT
    for workspace_id, count in counts.items():
        if workspace_id is None or count <= limit:
            continue
        logger.warning(
            "Workspace in-flight job count exceeds configured warning threshold",
            extra={
                "workspace_id": str(workspace_id),
                "in_flight_jobs": count,
                "limit": limit,
            },
        )
