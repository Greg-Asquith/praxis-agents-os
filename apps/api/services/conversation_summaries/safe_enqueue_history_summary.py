# apps/api/services/conversation_summaries/safe_enqueue_history_summary.py

"""Best-effort isolated enqueue for conversation history summaries."""

import logging
from contextlib import suppress
from uuid import UUID

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from services.conversation_summaries.enqueue_history_summary import enqueue_history_summary

logger = logging.getLogger(__name__)


async def safe_enqueue_history_summary(
    *,
    conversation_id: UUID,
    workspace_id: UUID,
    watermark_key: UUID,
) -> None:
    """Enqueue without affecting the completed agent-run transaction."""
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            try:
                await configure_async_db_session(db)
                await set_session_tenant_context(db, workspace_id=workspace_id)
                await enqueue_history_summary(
                    db,
                    conversation_id=conversation_id,
                    workspace_id=workspace_id,
                    watermark_key=watermark_key,
                )
                await db.commit()
            except Exception:
                with suppress(Exception):
                    await db.rollback()
                raise
    except Exception:
        logger.warning(
            "Conversation history-summary enqueue failed; continuing with plain trimming",
            exc_info=True,
            extra={
                "conversation_id": str(conversation_id),
                "watermark_key": str(watermark_key),
            },
        )
