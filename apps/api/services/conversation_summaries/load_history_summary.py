# apps/api/services/conversation_summaries/load_history_summary.py

"""Load one exact-watermark conversation history summary."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation_summary import ConversationSummary


async def load_history_summary(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    watermark_key: UUID | None,
) -> str | None:
    """Load the exact summary for a trim watermark, if it is ready."""
    if watermark_key is None:
        return None
    return await db.scalar(
        select(ConversationSummary.content).where(
            ConversationSummary.conversation_id == conversation_id,
            ConversationSummary.watermark_key == watermark_key,
            ConversationSummary.deleted.is_(False),
        )
    )
