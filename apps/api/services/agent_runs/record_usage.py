# apps/api/services/agent_runs/record_usage.py

"""Persist usage totals for a run."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from services.agent_runs.domain import RunUsageSnapshot


async def record_run_usage(
    db: AsyncSession, run: AgentRun, usage: RunUsageSnapshot
) -> AgentRun:
    """Persist usage totals (hot columns) plus the full RunUsage on usage_json."""
    run.input_tokens = usage.input_tokens
    run.input_tokens_cached = usage.input_tokens_cached
    run.output_tokens = usage.output_tokens
    run.requests = usage.requests
    run.tool_calls = usage.tool_calls
    run.usage_json = usage.raw_json
    await db.flush()
    return run
