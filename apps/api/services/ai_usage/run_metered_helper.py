# apps/api/services/ai_usage/run_metered_helper.py

"""Shared durable lifecycle for one helper-model invocation."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace

from pydantic_ai.usage import RunUsage

from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.record_durable import record_ai_usage_durable
from services.ai_usage.utils import usage_values

logger = logging.getLogger(__name__)


async def run_metered_helper[T](
    event: AIUsageEventData,
    call: Callable[[RunUsage], Awaitable[T]],
) -> T:
    """Run a helper with owned usage and durably record known usage in finally."""
    usage = RunUsage()
    try:
        return await call(usage)
    finally:
        try:
            await record_ai_usage_durable(replace(event, **usage_values(usage)))
        except Exception:
            logger.warning("Failed to finalize helper AI usage", exc_info=True)
