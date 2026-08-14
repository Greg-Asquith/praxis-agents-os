# apps/api/services/ai_usage/record_durable.py

"""Record AI usage in an isolated committed runtime-role transaction."""

import logging

from core.database import (
    configure_async_db_session,
    get_ai_usage_async_db_session_factory,
    set_session_tenant_context,
)
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.utils import add_event

logger = logging.getLogger(__name__)


async def record_ai_usage_durable(event: AIUsageEventData) -> bool:
    """Commit one event through the dedicated bounded metering pool."""
    if event.is_zero:
        return False
    try:
        session_factory = get_ai_usage_async_db_session_factory()
        async with session_factory() as db:
            await configure_async_db_session(db)
            await set_session_tenant_context(
                db,
                workspace_id=event.workspace_id,
                user_id=event.user_id,
            )
            add_event(db, event)
            await db.commit()
    except Exception:
        logger.warning("Failed to durably record AI usage", exc_info=True)
        return False
    return True
