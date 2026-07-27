# apps/api/services/jobs/handlers/embed_memory.py

"""Job adapter for agent-memory embeddings."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.registry import job_handler
from services.memories.domain import MEMORY_EMBED_JOB_KIND
from services.memories.embed_memory import embed_memory


@job_handler(kind=MEMORY_EMBED_JOB_KIND, timeout=120.0)
async def handle_embed_memory(db: AsyncSession, job: Job) -> None:
    """Embed the pending memory identified by the job payload."""
    await embed_memory(db, memory_id=UUID(str(job.payload["memory_id"])))
