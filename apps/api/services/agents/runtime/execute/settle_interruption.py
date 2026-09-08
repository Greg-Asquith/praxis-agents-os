# apps/api/services/agent/runtime/execute/settle_interruption.py

"""Settles usage and human stops after execution or failure is interrupted."""

import asyncio
from contextlib import suppress
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from services.agents.runtime.cancellation import is_agent_run_cancel_request
from services.agents.runtime.sinks import EventSink
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext

from .bounded_finalisation import bounded_finalisation
from .finalize import finalize_cancelled_run, finalize_interrupted_usage
from .utils import warn_accounting_incomplete


async def settle_interruption(
    db: AsyncSession,
    *,
    exc: asyncio.CancelledError,
    event_sink: EventSink,
    run_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    metering: AgentRunMeteringContext | None,
    max_wait: float,
) -> None:
    interrupted_usage = metering.event() if metering is not None else None
    human_cancel = is_agent_run_cancel_request(exc, run_id=run_id)
    # Rollback belongs to the execution task, never its isolated finaliser.
    with suppress(Exception, asyncio.CancelledError):
        async with asyncio.timeout(max_wait):
            await db.rollback()
    try:
        if human_cancel:
            operation = finalize_cancelled_run(
                event_sink=event_sink,
                run_id=run_id,
                workspace_id=workspace_id,
                user_id=user_id,
                metering=metering,
            )
        elif interrupted_usage is not None:
            operation = finalize_interrupted_usage(interrupted_usage)
        else:
            return
        settled = await bounded_finalisation(operation, max_wait=max_wait)
    except (Exception, asyncio.CancelledError):
        settled = False
    if not settled:
        warn_accounting_incomplete(metering, run_id)
