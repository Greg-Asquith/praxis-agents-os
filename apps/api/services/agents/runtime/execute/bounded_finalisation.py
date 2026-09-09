# apps/api/services/agents/runtime/execute/bounded_finalisation.py

"""Bounds isolated finalisation and retains ownership of unfinished cleanup."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from .utils import wait_until_deadline

logger = logging.getLogger(__name__)
_supervised: set[asyncio.Task] = set()


def _finished(task: asyncio.Task) -> None:
    _supervised.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Isolated run finalisation failed")


async def bounded_finalisation(operation: Coroutine[Any, Any, None], *, max_wait: float) -> bool:
    """Waits within a deadline, then cancels and joins isolated cleanup.

    The operation must own its sessions. A cancellation-resistant operation
    retains its own resources under supervision until its cleanup finishes.
    """
    task = asyncio.create_task(operation, name="agent-run-finalisation")
    cancellation: asyncio.CancelledError | None = None
    try:
        cancellation = await wait_until_deadline(task, max_wait=max_wait)
        if task.done():
            task.result()
            return True
        logger.warning("Agent run finalisation deadline exceeded")
        return False
    finally:
        if not task.done():
            task.cancel()
            join_cancellation = await wait_until_deadline(task, max_wait=max_wait)
            if cancellation is None:
                cancellation = join_cancellation
            if not task.done():
                _supervised.add(task)
                task.add_done_callback(_finished)
                logger.warning("Agent run finalisation cleanup remains supervised")
            if task.done():
                _finished(task)
        if cancellation is not None:
            raise cancellation
