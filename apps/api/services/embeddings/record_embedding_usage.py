# apps/api/services/embeddings/record_embedding_usage.py

"""Atomically record embedding-token usage."""

import logging
from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.embedding_usage import EmbeddingTokenUsage
from services.embeddings.get_embedding_usage import get_embedding_usage
from services.embeddings.utils import current_period_month

logger = logging.getLogger(__name__)


async def record_embedding_usage(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    tokens: int,
    period_month: date | None = None,
) -> int:
    """Atomically add tokens to a workspace month and return its new total."""
    requested_month = period_month or current_period_month()
    month = date(requested_month.year, requested_month.month, 1)
    if tokens <= 0:
        return await get_embedding_usage(
            db,
            workspace_id=workspace_id,
            period_month=month,
        )

    table = EmbeddingTokenUsage.__table__
    statement = insert(table).values(
        id=uuid4(),
        workspace_id=workspace_id,
        period_month=month,
        tokens_used=tokens,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_embedding_token_usage_workspace_month",
        set_={
            "tokens_used": table.c.tokens_used + statement.excluded.tokens_used,
            "updated_at": func.now(),
        },
    ).returning(table.c.tokens_used)
    total = int((await db.execute(statement)).scalar_one())

    budget = settings.EMBEDDINGS_MONTHLY_TOKEN_BUDGET
    if total - tokens <= budget < total:
        logger.warning(
            "Workspace embedding-token usage crossed its soft monthly budget",
            extra={
                "workspace_id": str(workspace_id),
                "tokens_used": total,
                "token_budget": budget,
            },
        )
    return total
