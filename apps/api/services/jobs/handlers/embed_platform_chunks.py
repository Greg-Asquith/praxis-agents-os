# apps/api/services/jobs/handlers/embed_platform_chunks.py

"""Actor-authorised platform knowledge job adapter."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.registry import job_handler
from services.kb.embed_platform_chunks import embed_platform_chunks
from services.kb.platform_job_utils import require_platform_job_actor


@job_handler(kind="kb.platform_embed_chunks", timeout=600.0)
async def handle_embed_platform_chunks(db: AsyncSession, job: Job) -> None:
    """Validates authority before entering the maintenance pipeline."""
    await require_platform_job_actor(db, job)
    await db.commit()
    await embed_platform_chunks(job)
