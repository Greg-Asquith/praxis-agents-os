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
from services.ai_usage.domain import validate_usage_owner
from services.embeddings.get_embedding_usage import get_embedding_usage
from services.embeddings.utils import current_period_month
from utils.content import ContentScope

logger = logging.getLogger(__name__)


async def record_embedding_usage(
    db: AsyncSession,
    *,
    workspace_id: UUID | None,
    scope: ContentScope = ContentScope.WORKSPACE,
    tokens: int,
    period_month: date | None = None,
) -> int:
    """Adds tokens to the selected owner and month and returns its new total."""
    validate_usage_owner(scope, workspace_id)
    requested_month = period_month or current_period_month()
    month = date(requested_month.year, requested_month.month, 1)
    if tokens <= 0:
        return await get_embedding_usage(
            db,
            workspace_id=workspace_id,
            scope=scope,
            period_month=month,
        )

    table = EmbeddingTokenUsage.__table__
    statement = insert(table).values(
        id=uuid4(),
        workspace_id=workspace_id,
        scope=scope,
        period_month=month,
        tokens_used=tokens,
    )
    conflict_target = (
        {"index_elements": [table.c.period_month], "index_where": table.c.scope == "platform"}
        if scope == ContentScope.PLATFORM
        else {"constraint": "uq_embedding_token_usage_workspace_month"}
    )
    statement = statement.on_conflict_do_update(
        **conflict_target,
        set_={
            "tokens_used": table.c.tokens_used + statement.excluded.tokens_used,
            "updated_at": func.now(),
        },
    ).returning(table.c.tokens_used)
    total = int((await db.execute(statement)).scalar_one())

    budget = settings.EMBEDDINGS_MONTHLY_TOKEN_BUDGET
    if scope == ContentScope.WORKSPACE and total - tokens <= budget < total:
        logger.warning(
            "Workspace embedding-token usage crossed its soft monthly budget",
            extra={
                "workspace_id": str(workspace_id),
                "tokens_used": total,
                "token_budget": budget,
            },
        )
    return total
