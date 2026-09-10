# apps/api/services/ai_usage/record_durable.py

"""Records AI usage in an isolated transaction for its explicit owner."""

import logging

from core.database import (
    configure_async_db_session,
    get_ai_usage_async_db_session_factory,
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
)
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.utils import add_event
from services.embeddings.record_embedding_usage import record_embedding_usage
from utils.content import ContentScope

logger = logging.getLogger(__name__)


async def record_ai_usage_durable(event: AIUsageEventData) -> bool:
    """Commits workspace usage through the metering pool and platform usage as maintenance."""
    if event.is_zero:
        return False
    try:
        session_factory = (
            get_maintenance_async_db_session_factory()
            if event.scope == ContentScope.PLATFORM
            else get_ai_usage_async_db_session_factory()
        )
        async with session_factory() as db:
            await configure_async_db_session(db)
            if event.scope == ContentScope.WORKSPACE:
                await set_session_tenant_context(
                    db,
                    workspace_id=event.workspace_id,
                    user_id=event.user_id,
                )
            add_event(db, event)
            if event.scope == ContentScope.PLATFORM and event.purpose == "embedding_kb_ingest":
                await record_embedding_usage(
                    db, workspace_id=None, scope=event.scope, tokens=event.input_tokens
                )
            await db.commit()
    except Exception:
        logger.warning("Failed to durably record AI usage", exc_info=True)
        return False
    return True
