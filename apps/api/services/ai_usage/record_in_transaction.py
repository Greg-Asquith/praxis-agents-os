# apps/api/services/ai_usage/record_in_transaction.py

"""Record AI usage inside the caller transaction without poisoning it on failure."""

import logging
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_usage_event import AIUsageEvent
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
            if event.event_id is None:
                add_event(db, event)
                await db.flush()
            else:
                values = asdict(event)
                values["id"] = values.pop("event_id")
                inserted = await db.scalar(
                    insert(AIUsageEvent)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[AIUsageEvent.id])
                    .returning(AIUsageEvent.id)
                )
                if inserted is None:
                    existing = await db.scalar(
                        select(AIUsageEvent).where(
                            AIUsageEvent.id == event.event_id,
                            AIUsageEvent.workspace_id == event.workspace_id,
                        )
                    )
                    if existing is None or any(
                        getattr(existing, name) != value for name, value in values.items()
                    ):
                        logger.warning(
                            "AI usage settlement payload mismatch",
                            extra={"event_id": str(event.event_id)},
                        )
                        return False
    except Exception:
        logger.warning(
            "AI usage accounting incomplete",
            extra={
                "event_id": str(event.event_id),
                "agent_run_id": str(event.run_id),
                "provider": event.provider,
                "model": event.model,
                "invocation_id": (event.details or {}).get("invocation_id"),
                "input_tokens": event.input_tokens,
                "cache_read_tokens": event.cache_read_tokens,
                "cache_write_tokens": event.cache_write_tokens,
                "output_tokens": event.output_tokens,
                "requests": event.requests,
            },
        )
        return False
    return True
