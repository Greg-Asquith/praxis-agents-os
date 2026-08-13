# apps/api/workers/main.py

"""Worker supervisor for scheduled agent runs and generic jobs."""

import asyncio
import logging
import signal
from contextlib import suppress

from core.database import (
    close_db_connections,
    configure_async_db_session,
    get_maintenance_async_db_session_factory,
)
from core.logging import setup_logging
from core.settings import settings
from services.agents.runtime.code_mode import close_code_mode_executor
from services.security import ensure_application_encryption_keys_loaded
from workers import agent_runner, job_runner

setup_logging()
logger = logging.getLogger(__name__)


async def main() -> int:
    """Run both worker loops under one shutdown event."""
    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    try:
        session_factory = get_maintenance_async_db_session_factory()
        async with session_factory() as db:
            await configure_async_db_session(db)
            await ensure_application_encryption_keys_loaded(db)
        if settings.WORKER_MODE == "drain":
            return await _run_drain_mode(shutdown_event)
        return await _run_forever_mode(shutdown_event)
    finally:
        try:
            await close_code_mode_executor()
        finally:
            await close_db_connections()


async def _run_forever_mode(shutdown_event: asyncio.Event) -> int:
    """Supervise the long-running polling loops."""
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


async def _run_drain_mode(shutdown_event: asyncio.Event) -> int:
    """Supervise both runners until drained or the execution budget expires."""
    budget_task = asyncio.create_task(
        _expire_drain_budget(shutdown_event),
        name="worker-drain-budget",
    )
    runner_tasks: set[asyncio.Task[int]] = set()

    try:
        while not shutdown_event.is_set():
            runner_tasks = {
                asyncio.create_task(
                    agent_runner.run_drain(shutdown_event=shutdown_event),
                    name="scheduled-agent-runner",
                ),
                asyncio.create_task(
                    job_runner.run_drain(shutdown_event=shutdown_event),
                    name="generic-job-runner",
                ),
            }
            done, pending = await asyncio.wait(
                runner_tasks,
                return_when=asyncio.FIRST_EXCEPTION,
            )
            failed = [
                task for task in done if not task.cancelled() and task.exception() is not None
            ]
            if failed:
                for task in failed:
                    exception = task.exception()
                    if exception is None:
                        continue
                    logger.error(
                        "Worker drain loop exited with an exception",
                        exc_info=(type(exception), exception, exception.__traceback__),
                        extra={"task": task.get_name()},
                    )
                shutdown_event.set()
                await _drain_pending_tasks(pending)
                return 1

            claimed_count = sum(task.result() for task in done)
            if claimed_count == 0:
                return 0

        return 0
    finally:
        shutdown_event.set()
        budget_task.cancel()
        with suppress(asyncio.CancelledError):
            await budget_task
        for task in runner_tasks:
            task.cancel()
        await asyncio.gather(*runner_tasks, return_exceptions=True)


async def _expire_drain_budget(shutdown_event: asyncio.Event) -> None:
    """Request a clean drain stop once its wall-clock budget is exhausted."""
    try:
        await asyncio.wait_for(
            shutdown_event.wait(),
            timeout=settings.WORKER_DRAIN_MAX_SECONDS,
        )
    except TimeoutError:
        logger.info(
            "Worker drain budget expired; finishing in-flight work",
            extra={"max_seconds": settings.WORKER_DRAIN_MAX_SECONDS},
        )
        shutdown_event.set()


async def _drain_pending_tasks(
    pending: set[asyncio.Task[int]] | set[asyncio.Task[None]],
) -> None:
    if not pending:
        return

    timeout_seconds = max(
        settings.AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS,
        settings.JOBS_WORKER_SHUTDOWN_SECONDS,
    )
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
