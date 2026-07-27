# apps/api/services/conversation_summaries/enqueue_history_summary.py

"""Enqueue one missing conversation history summary."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation_summary import ConversationSummary
from models.jobs import Job
from services.conversation_summaries.domain import SUMMARIZE_HISTORY_JOB_KIND
from services.jobs.enqueue_job import enqueue_job


async def enqueue_history_summary(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    workspace_id: UUID,
    watermark_key: UUID,
) -> Job | None:
    """Enqueue a missing summary once per conversation watermark."""
    existing = await db.scalar(
        select(ConversationSummary.id).where(
            ConversationSummary.conversation_id == conversation_id,
            ConversationSummary.watermark_key == watermark_key,
            ConversationSummary.deleted.is_(False),
        )
    )
    if existing is not None:
        return None
    return await enqueue_job(
        db,
        kind=SUMMARIZE_HISTORY_JOB_KIND,
        workspace_id=workspace_id,
        subject_type="conversation",
        subject_id=conversation_id,
        payload={"watermark_key": str(watermark_key)},
        content_hash=str(watermark_key),
    )
