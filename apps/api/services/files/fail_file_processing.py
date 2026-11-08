# apps/api/services/files/fail_file_processing.py

"""Fails a File's processing once its job has no attempts left."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.files.utils import lock_current_revision_file, parse_extraction_payload_ids

_SLOW_FAILURE_CODES = frozenset({"handler_timeout", "lease_expired"})
SLOW_FAILURE_MESSAGE = "Preparing this file took too long. Upload it again to retry."


async def fail_file_processing(db: AsyncSession, job: Job) -> None:
    """Marks the job's revision failed if it's still current and unfinished."""
    file_id, revision_id = parse_extraction_payload_ids(job.payload or {})
    if file_id is None or revision_id is None:
        return
    file = await lock_current_revision_file(
        db, file_id=file_id, revision_id=revision_id, workspace_id=job.workspace_id
    )
    if file is None or file.processing_status not in {"pending", "processing"}:
        return
    file.processing_status = "error"
    file.processing_error = (
        SLOW_FAILURE_MESSAGE
        if job.last_error_code in _SLOW_FAILURE_CODES
        else job.last_error_message
    )
    await db.flush()
