# apps/api/services/agent/runtime/execute/settle_failure.py

"""Bounds ordinary failure persistence and records incomplete accounting."""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agents.runtime.sinks import EventSink
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext

from .finalize import emit_failure_events
from .utils import warn_accounting_incomplete


async def settle_failure(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    started: bool,
    run_id: UUID,
    exc: Exception,
    metering: AgentRunMeteringContext | None,
    max_wait: float,
    owner_instance_id: str | None = None,
) -> AgentRun | None:
    if metering is not None:
        metering.freeze()
    try:
        async with asyncio.timeout(max_wait):
            return await emit_failure_events(
                db,
                event_sink=event_sink,
                started=started,
                run_id=run_id,
                exc=exc,
                metering=metering,
                owner_instance_id=owner_instance_id,
            )
    except Exception:
        warn_accounting_incomplete(metering, run_id)
        return None
