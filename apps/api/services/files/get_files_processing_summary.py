# apps/api/services/files/get_files_processing_summary.py

"""Summarize workspace file processing state."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FILE_PROCESSING_STATUSES, File
from models.workspace import Workspace
from services.files.domain import FilesProcessingSummary
from services.jobs import count_in_flight_jobs


async def get_files_processing_summary(
    db: AsyncSession,
    *,
    workspace: Workspace,
) -> FilesProcessingSummary:
    """Return per-status file counts and in-flight jobs for a workspace."""
    rows = await db.execute(
        select(File.processing_status, func.count(File.id))
        .where(
            File.workspace_id == workspace.id,
            File.deleted.is_(False),
        )
        .group_by(File.processing_status)
    )
    counts = dict.fromkeys(FILE_PROCESSING_STATUSES, 0)
    counts.update({status: int(count) for status, count in rows.all()})
    job_counts = await count_in_flight_jobs(
        db,
        workspace_id=workspace.id,
        kind="files.extract",
    )
    return FilesProcessingSummary(
        pending=counts["pending"],
        processing=counts["processing"],
        ready=counts["ready"],
        error=counts["error"],
        in_flight_jobs=job_counts.get(workspace.id, 0),
    )
