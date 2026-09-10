# apps/api/services/embeddings/get_embedding_usage.py

"""Read embedding-token usage counters."""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.embedding_usage import EmbeddingTokenUsage
from services.ai_usage.domain import validate_usage_owner
from services.embeddings.utils import current_period_month
from utils.content import ContentScope


async def get_embedding_usage(
    db: AsyncSession,
    *,
    workspace_id: UUID | None,
    scope: ContentScope = ContentScope.WORKSPACE,
    period_month: date | None = None,
) -> int:
    """Returns the selected owner and month token total."""
    validate_usage_owner(scope, workspace_id)
    total = await db.scalar(
        select(EmbeddingTokenUsage.tokens_used).where(
            EmbeddingTokenUsage.workspace_id == workspace_id,
            EmbeddingTokenUsage.scope == scope,
            EmbeddingTokenUsage.period_month == (period_month or current_period_month()),
        )
    )
    return int(total or 0)
