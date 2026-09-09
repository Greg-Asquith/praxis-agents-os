# apps/api/services/agent/runtime/execute/utils.py

"""Shared finalisation deadlines and accounting evidence."""

import asyncio
import logging
from uuid import UUID

from services.ai_usage.agent_run_accounting import AgentRunMeteringContext

logger = logging.getLogger(__name__)


def warn_accounting_incomplete(metering: AgentRunMeteringContext | None, run_id: UUID) -> None:
    if metering is None:
        return
    logger.warning(
        "Agent run accounting incomplete",
        extra={
            "invocation_id": str(metering.invocation_id),
            "agent_run_id": str(run_id),
            "provider": metering.provider,
            "model": metering.model,
            **metering.freeze(),
        },
    )


async def wait_until_deadline(
    task: asyncio.Task, *, max_wait: float
) -> asyncio.CancelledError | None:
    """Waits through repeated cancellation without extending the deadline."""
    deadline = asyncio.get_running_loop().time() + max_wait
    cancellation = None
    while not task.done():
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait({task}, timeout=remaining)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
    return cancellation
