# apps/api/services/ai_usage/record_agent_run_fallback.py

"""Record failure/cancellation usage after subtracting committed descendants."""

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.domain import PURPOSE_AGENT_RUN, AIUsageEventData
from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction

_COUNTERS = (
    "input_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "output_tokens",
    "requests",
)


async def record_agent_run_fallback(
    db: AsyncSession,
    *,
    run: AgentRun,
    metering: AgentRunMeteringContext | None,
) -> bool:
    """Record this invocation's accumulator delta less descendant run events."""
    if metering is None:
        return False
    delta = metering.accumulator_delta()
    descendant = await _descendant_usage_since(
        db,
        run_id=run.id,
        invocation_started_at=metering.invocation_started_at,
    )
    values = {name: max(0, delta[name] - descendant[name]) for name in _COUNTERS}
    return await record_ai_usage_in_transaction(
        db,
        AIUsageEventData(
            workspace_id=run.workspace_id,
            provider=metering.provider,
            model=metering.model,
            purpose=PURPOSE_AGENT_RUN,
            agent_id=run.agent_id,
            user_id=run.user_id,
            run_id=run.id,
            conversation_id=run.conversation_id,
            details={"usage_source": "accumulator_delta"},
            **values,
        ),
    )


async def _descendant_usage_since(
    db: AsyncSession,
    *,
    run_id: Any,
    invocation_started_at: datetime,
) -> dict[str, int]:
    result = (
        await db.execute(
            sa.text(
                """
                WITH RECURSIVE descendants AS (
                    SELECT id FROM agent_runs WHERE parent_run_id = :run_id
                    UNION ALL
                    SELECT child.id
                    FROM agent_runs AS child
                    JOIN descendants AS parent ON child.parent_run_id = parent.id
                )
                SELECT
                    COALESCE(SUM(event.input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(event.cache_read_tokens), 0) AS cache_read_tokens,
                    COALESCE(SUM(event.cache_write_tokens), 0) AS cache_write_tokens,
                    COALESCE(SUM(event.output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(event.requests), 0) AS requests
                FROM ai_usage_events AS event
                JOIN descendants ON descendants.id = event.run_id
                WHERE event.purpose = 'agent_run'
                  AND event.occurred_at >= :invocation_started_at
                """
            ),
            {"run_id": run_id, "invocation_started_at": invocation_started_at},
        )
    ).one()
    mapping: dict[str, Any] = dict(result._mapping)
    return {name: int(mapping[name]) for name in _COUNTERS}
