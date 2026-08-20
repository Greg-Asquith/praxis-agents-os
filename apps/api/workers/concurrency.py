# apps/api/workers/concurrency.py

"""Shared worker-process concurrency controls."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from core.settings import settings

_worker_run_semaphore: asyncio.Semaphore | None = None
_worker_run_loop: asyncio.AbstractEventLoop | None = None
_worker_run_limit: int | None = None


def _get_worker_run_semaphore() -> asyncio.Semaphore:
    """Returns the semaphore shared by both worker queues in this event loop."""
    global _worker_run_limit, _worker_run_loop, _worker_run_semaphore

    loop = asyncio.get_running_loop()
    limit = settings.WORKER_MAX_CONCURRENT_RUNS
    if _worker_run_semaphore is None or _worker_run_loop is not loop or _worker_run_limit != limit:
        _worker_run_semaphore = asyncio.Semaphore(limit)
        _worker_run_loop = loop
        _worker_run_limit = limit
    return _worker_run_semaphore


@asynccontextmanager
async def worker_run_slot() -> AsyncIterator[None]:
    """Limits active scheduled runs and generic handlers across one worker process."""
    async with _get_worker_run_semaphore():
        yield


async def run_worker_batch(
    *,
    max_items: int,
    run_one: Callable[[], Awaitable[bool]],
    shutdown_event: asyncio.Event | None = None,
) -> int:
    """Runs up to ``max_items`` under shared admission and awaits every item."""
    next_item = 0

    async def run_lane() -> int:
        nonlocal next_item
        completed = 0
        while True:
            async with worker_run_slot():
                if shutdown_event is not None and shutdown_event.is_set():
                    return completed
                if next_item >= max_items:
                    return completed
                next_item += 1
                if not await run_one():
                    return completed
                completed += 1

    results = await asyncio.gather(
        *(run_lane() for _ in range(min(max_items, settings.WORKER_MAX_CONCURRENT_RUNS))),
        return_exceptions=True,
    )
    errors: list[Exception] = []
    completed = 0
    for result in results:
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, Exception):
            errors.append(result)
            continue
        completed += result
    if errors:
        raise ExceptionGroup("Worker batch execution failed", errors)
    return completed
