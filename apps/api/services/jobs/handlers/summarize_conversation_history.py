# apps/api/services/jobs/handlers/summarize_conversation_history.py

"""Run out-of-band conversation history compaction."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.jobs import Job
from services.conversation_summaries.domain import SUMMARIZE_HISTORY_JOB_KIND
from services.conversation_summaries.summarize_history_job import summarize_history_job
from services.jobs.registry import job_handler


@job_handler(kind=SUMMARIZE_HISTORY_JOB_KIND, timeout=120.0, max_attempts=3)
async def summarize_conversation_history(db: AsyncSession, job: Job) -> None:
    """Generate one missing cache-stable conversation summary."""
    await summarize_history_job(db, job)
