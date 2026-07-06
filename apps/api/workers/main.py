# apps/api/workers/main.py

"""Worker supervisor for scheduled agent runs and generic jobs."""

import asyncio
import logging
import signal
from contextlib import suppress

from core.database import close_db_connections
from core.logging import setup_logging
from core.settings import settings
from workers import agent_runner, job_runner

setup_logging()
logger = logging.getLogger(__name__)


async def main() -> int:
    """Run both worker loops under one shutdown event."""
    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    tasks = {
        asyncio.create_task(
            agent_runner.run_forever(shutdown_event=shutdown_event),
            name="scheduled-agent-runner",
        ),
        asyncio.create_task(
            job_runner.run_forever(shutdown_event=shutdown_event),
            name="generic-job-runner",
        ),
    }

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        unexpected = not shutdown_event.is_set()
        for task in done:
            exception = task.exception()
            if exception is not None:
                unexpected = True
                logger.error(
                    "Worker loop exited with an exception",
                    exc_info=(type(exception), exception, exception.__traceback__),
                    extra={"task": task.get_name()},
                )
            elif not shutdown_event.is_set():
                logger.error("Worker loop exited unexpectedly", extra={"task": task.get_name()})

        shutdown_event.set()
        await _drain_pending_tasks(pending)
        return 1 if unexpected else 0
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await close_db_connections()


async def _drain_pending_tasks(pending: set[asyncio.Task[None]]) -> None:
    if not pending:
        return

    timeout_seconds = settings.AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS
    logger.info(
        "Waiting for worker loops to shut down",
        extra={"timeout_seconds": timeout_seconds},
    )
    try:
        await asyncio.wait_for(asyncio.gather(*pending), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning(
            "Worker loops exceeded shutdown timeout; cancelling",
            extra={"timeout_seconds": timeout_seconds},
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, shutdown_event.set)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
