# apps/api/services/ai_usage/record_in_transaction.py

"""Record AI usage inside the caller transaction without poisoning it on failure."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.utils import add_event

logger = logging.getLogger(__name__)


async def record_ai_usage_in_transaction(
    db: AsyncSession,
    event: AIUsageEventData,
) -> bool:
    """Insert through a savepoint; return false when metering persistence fails."""
    if event.is_zero:
        return False
    try:
        async with db.begin_nested():
            add_event(db, event)
            await db.flush()
    except Exception:
        logger.warning("Failed to record AI usage in caller transaction", exc_info=True)
        return False
    return True
