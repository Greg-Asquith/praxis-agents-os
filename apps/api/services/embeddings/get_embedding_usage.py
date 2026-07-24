# apps/api/services/embeddings/get_embedding_usage.py

"""Read embedding-token usage counters."""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.embedding_usage import EmbeddingTokenUsage
from services.embeddings.utils import current_period_month


async def get_embedding_usage(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    period_month: date | None = None,
) -> int:
    """Return one workspace-month total.

    This counter intentionally has no route yet. The knowledge-base UI owns
    the pending admin-visible usage surface.
    """
    total = await db.scalar(
        select(EmbeddingTokenUsage.tokens_used).where(
            EmbeddingTokenUsage.workspace_id == workspace_id,
            EmbeddingTokenUsage.period_month == (period_month or current_period_month()),
        )
    )
    return int(total or 0)
