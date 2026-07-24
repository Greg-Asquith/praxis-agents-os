# apps/api/services/jobs/handlers/embed_kb_chunks.py

"""Job adapter for knowledge-base embeddings."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.jobs.registry import job_handler
from services.kb.embed_chunks import embed_kb_chunks

EMBED_KB_CHUNKS_KIND = "kb.embed_chunks"


@job_handler(kind=EMBED_KB_CHUNKS_KIND, timeout=600.0)
async def handle_embed_kb_chunks(db: AsyncSession, job: Job) -> None:
    """Embed the job's pending document chunks."""
    if job.subject_id is None:
        return
    await embed_kb_chunks(
        db,
        document_id=job.subject_id,
        workspace_id=job.workspace_id,
    )
