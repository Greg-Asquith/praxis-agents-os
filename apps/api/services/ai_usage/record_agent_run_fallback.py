# apps/api/services/ai_usage/record_agent_run_fallback.py

"""Settles frozen invocation usage without depending on child ledger writes."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction


async def record_agent_run_fallback(
    db: AsyncSession,
    *,
    run: AgentRun,
    metering: AgentRunMeteringContext | None,
) -> bool:
    """Records the invocation once, including after a competing terminal verdict."""
    if metering is None:
        return False
    return await record_ai_usage_in_transaction(db, metering.event(run))
