# apps/api/services/jobs/handlers/ingest_platform_document.py

"""Actor-authorised platform knowledge job adapter."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.registry import job_handler
from services.kb.ingest_platform_document import ingest_platform_document
from services.kb.platform_job_utils import require_platform_job_actor


@job_handler(kind="kb.platform_ingest_document", timeout=600.0)
async def handle_ingest_platform_document(db: AsyncSession, job: Job) -> None:
    """Validates authority before entering the maintenance pipeline."""
    await require_platform_job_actor(db, job)
    await db.commit()
    await ingest_platform_document(job)
