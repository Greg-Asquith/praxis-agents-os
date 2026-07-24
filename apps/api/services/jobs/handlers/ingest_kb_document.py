# apps/api/services/jobs/handlers/ingest_kb_document.py

"""Job adapter for knowledge-base ingestion."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.registry import job_handler
from services.kb.ingest_document import ingest_kb_document

INGEST_KB_DOCUMENT_KIND = "kb.ingest_document"


@job_handler(kind=INGEST_KB_DOCUMENT_KIND, timeout=600.0)
async def handle_ingest_kb_document(db: AsyncSession, job: Job) -> None:
    """Ingest the job's document subject."""
    if job.subject_id is None:
        return
    await ingest_kb_document(
        db,
        document_id=job.subject_id,
        workspace_id=job.workspace_id,
        initiated_by_user_id=job.initiated_by_user_id,
    )
