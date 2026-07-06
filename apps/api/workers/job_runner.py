# apps/api/workers/job_runner.py

"""Generic background job runner process."""

import argparse
import asyncio
import logging
import os
import signal
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from core.database import (
    close_db_connections,
    configure_async_db_session,
    get_async_db_session_factory,
)
from core.logging import setup_logging
from core.settings import settings
from models.jobs import Job
from services.jobs.claim_jobs import claim_jobs
from services.jobs.domain import JOB_STATUS_RUNNING
from services.jobs.finalize_job import finalize_job_failure, finalize_job_success
from services.jobs.handlers.sweep_deleted_files import ensure_files_sweep_job
from services.jobs.handlers.sweep_rate_limit_attempts import ensure_rate_limit_sweep_job
from services.jobs.handlers.sweep_terminal_jobs import ensure_sweep_job
from services.jobs.reclaim_stale_jobs import reclaim_stale_jobs
from services.jobs.registry import get_job_handler

setup_logging()
logger = logging.getLogger(__name__)


async def run_once(*, owner_instance_id: str | None = None) -> int:
    """Reclaim stale work, claim due jobs, and execute one claimed batch."""
    owner_id = owner_instance_id or _owner_instance_id()
    session_factory = get_async_db_session_factory()

    async with session_factory() as db:
        await configure_async_db_session(db)
        reclaimed_count = await reclaim_stale_jobs(db)
        if reclaimed_count:
            logger.info("Reclaimed stale generic jobs", extra={"count": reclaimed_count})
        await ensure_sweep_job(db)
        await ensure_files_sweep_job(db)
        await ensure_rate_limit_sweep_job(db)
        claimed_jobs = await claim_jobs(
            db,
            owner_instance_id=owner_id,
            batch_size=settings.JOBS_WORKER_BATCH_SIZE,
            lock_ttl_seconds=settings.JOBS_LOCK_TTL_SECONDS,
        )
        job_ids = [job.id for job in claimed_jobs]
        await db.commit()

    for job_id in job_ids:
        await execute_claimed_job(job_id, owner_instance_id=owner_id)

    return len(job_ids)


async def execute_claimed_job(job_id: UUID, *, owner_instance_id: str) -> None:
    """Execute one claimed job and finalize the attempt."""
    definition = None
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        now_utc = datetime.now(UTC)
        job = await db.scalar(
            select(Job)
            .where(
                Job.id == job_id,
                Job.status == JOB_STATUS_RUNNING,
                Job.locked_by == owner_instance_id,
                Job.lock_expires_at.is_not(None),
                Job.lock_expires_at > now_utc,
            )
            .with_for_update()
        )
        if job is None:
            await db.rollback()
            logger.warning(
                "Claimed job is no longer executable by this worker",
                extra={"job_id": str(job_id), "owner_instance_id": owner_instance_id},
            )
            return

        definition = get_job_handler(job.kind)
        if definition is None:
            await finalize_job_failure(
                db,
                job,
                code="unknown_kind",
                message=f"No handler is registered for job kind '{job.kind}'",
                force_terminal=True,
            )
            await db.commit()
            logger.error(
                "Generic job failed because its handler is not registered",
                extra={"job_id": str(job.id), "kind": job.kind},
            )
            return

        try:
            timeout_seconds = definition.timeout or settings.JOBS_HANDLER_TIMEOUT_SECONDS
            await asyncio.wait_for(definition.function(db, job), timeout=timeout_seconds)
            await finalize_job_success(db, job)
            await db.commit()
            logger.info(
                "Generic job completed",
                extra={"job_id": str(job.id), "kind": job.kind},
            )
        except TimeoutError:
            await db.rollback()
            await _record_job_failure(
                job_id,
                owner_instance_id=owner_instance_id,
                code="handler_timeout",
                message=f"Job handler exceeded timeout for kind '{definition.kind}'",
            )
        except Exception as exc:
            await db.rollback()
            logger.exception(
                "Generic job handler failed",
                extra={"job_id": str(job_id), "kind": definition.kind},
            )
            await _record_job_failure(
                job_id,
                owner_instance_id=owner_instance_id,
                code=exc.__class__.__name__,
                message=str(exc) or exc.__class__.__name__,
            )


async def run_forever(
    *,
    shutdown_event: asyncio.Event,
    owner_instance_id: str | None = None,
) -> None:
    """Poll for generic jobs until shutdown is requested."""
    owner_id = owner_instance_id or _owner_instance_id()
    while not shutdown_event.is_set():
        try:
            claimed_count = await _run_once_until_shutdown(
                shutdown_event=shutdown_event,
                owner_instance_id=owner_id,
            )
            if claimed_count:
                logger.info("Executed generic job batch", extra={"count": claimed_count})
        except Exception:
            logger.exception("Generic job runner polling pass failed")

        if shutdown_event.is_set():
            break

        with suppress(TimeoutError):
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=settings.JOBS_WORKER_POLL_SECONDS,
            )


async def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the generic job runner."""
    parser = argparse.ArgumentParser(description="Run generic Praxis background jobs.")
    parser.add_argument("--once", action="store_true", help="Run one polling pass and exit.")
    args = parser.parse_args(argv)

    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    try:
        if args.once:
            await run_once()
            return 0

        await run_forever(shutdown_event=shutdown_event)
        return 0
    finally:
        await close_db_connections()


async def _record_job_failure(
    job_id: UUID,
    *,
    owner_instance_id: str,
    code: str,
    message: str,
) -> None:
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        try:
            job = await db.scalar(
                select(Job)
                .where(
                    Job.id == job_id,
                    Job.status == JOB_STATUS_RUNNING,
                    Job.locked_by == owner_instance_id,
                )
                .with_for_update()
            )
            if job is None:
                await db.rollback()
                logger.warning(
                    "Skipped recording failure for job no longer owned by this worker",
                    extra={"job_id": str(job_id), "owner_instance_id": owner_instance_id},
                )
                return
            terminal = await finalize_job_failure(db, job, code=code, message=message)
            await db.commit()
            logger.warning(
                "Generic job attempt failed",
                extra={
                    "job_id": str(job.id),
                    "kind": job.kind,
                    "status": job.status,
                    "terminal": terminal,
                },
            )
        except Exception:
            await db.rollback()
            logger.exception("Failed to record generic job failure", extra={"job_id": str(job_id)})


async def _run_once_until_shutdown(
    *,
    shutdown_event: asyncio.Event,
    owner_instance_id: str,
) -> int | None:
    polling_task = asyncio.create_task(
        run_once(owner_instance_id=owner_instance_id),
        name="generic-job-runner-pass",
    )
    shutdown_task = asyncio.create_task(
        shutdown_event.wait(),
        name="generic-job-runner-shutdown-wait",
    )
    try:
        done, _pending = await asyncio.wait(
            {polling_task, shutdown_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if polling_task in done:
            return polling_task.result()

        timeout_seconds = settings.AGENT_SCHEDULE_WORKER_SHUTDOWN_SECONDS
        logger.info(
            "Shutdown requested; waiting for generic job runner pass",
            extra={"timeout_seconds": timeout_seconds},
        )
        try:
            return await asyncio.wait_for(polling_task, timeout=timeout_seconds)
        except TimeoutError:
            logger.warning(
                "Generic job runner pass exceeded shutdown timeout; cancelling",
                extra={"timeout_seconds": timeout_seconds},
            )
            polling_task.cancel()
            with suppress(asyncio.CancelledError):
                await polling_task
            return None
    finally:
        shutdown_task.cancel()
        with suppress(asyncio.CancelledError):
            await shutdown_task


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, shutdown_event.set)


def _owner_instance_id() -> str:
    return f"{os.uname().nodename}:{os.getpid()}"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
