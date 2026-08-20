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
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
)
from core.logging import setup_logging
from core.settings import settings
from models.jobs import Job
from services.integrations.discovery.recover_orphaned import recover_orphaned_discoveries
from services.integrations.discovery.rediscover_stale import (
    ensure_integrations_rediscover_job,
)
from services.integrations.discovery.sweep_stale import ensure_integrations_sweep_job
from services.integrations.events import ensure_refresh_webhooks_job
from services.jobs.claim_jobs import claim_jobs
from services.jobs.domain import JOB_STATUS_RUNNING
from services.jobs.finalize_job import finalize_job_failure, finalize_job_success
from services.jobs.handlers.sweep_deleted_files import ensure_files_sweep_job
from services.jobs.handlers.sweep_expired_agent_run_approvals import (
    ensure_agent_run_approval_sweep_job,
)
from services.jobs.handlers.sweep_expired_artifact_shares import (
    ensure_artifact_shares_sweep_job,
)
from services.jobs.handlers.sweep_expired_audit_events import ensure_audit_event_sweep_job
from services.jobs.handlers.sweep_expired_scratch import ensure_scratch_sweep_job
from services.jobs.handlers.sweep_expired_security_events import (
    ensure_security_event_sweep_job,
)
from services.jobs.handlers.sweep_rate_limit_attempts import ensure_rate_limit_sweep_job
from services.jobs.handlers.sweep_terminal_jobs import ensure_sweep_job
from services.jobs.heartbeat_job_lease import heartbeat_job_lease
from services.jobs.log_concurrency_warnings import log_job_concurrency_warnings
from services.jobs.reclaim_stale_jobs import reclaim_stale_jobs
from services.jobs.registry import get_job_handler
from services.memories.ensure_sweep_job import ensure_memory_sweep_job
from services.security import ensure_application_encryption_keys_loaded
from workers.concurrency import run_worker_batch, worker_run_slot

setup_logging()
logger = logging.getLogger(__name__)


async def run_once(
    *,
    owner_instance_id: str | None = None,
    batch_size: int | None = None,
    shutdown_event: asyncio.Event | None = None,
) -> int:
    """Reclaim stale work, claim due jobs, and execute one claimed batch."""
    owner_id = owner_instance_id or _owner_instance_id()
    session_factory = get_maintenance_async_db_session_factory()

    async with session_factory() as db:
        await configure_async_db_session(db)
        reclaimed_count = await reclaim_stale_jobs(db)
        if reclaimed_count:
            logger.info("Reclaimed stale generic jobs", extra={"count": reclaimed_count})
        recovered_count = await recover_orphaned_discoveries(db)
        if recovered_count:
            logger.warning(
                "Recovered integration discoveries without in-flight jobs",
                extra={"count": recovered_count},
            )
        await ensure_sweep_job(db)
        await ensure_files_sweep_job(db)
        await ensure_artifact_shares_sweep_job(db)
        await ensure_agent_run_approval_sweep_job(db)
        await ensure_audit_event_sweep_job(db)
        await ensure_security_event_sweep_job(db)
        await ensure_scratch_sweep_job(db)
        await ensure_rate_limit_sweep_job(db)
        await ensure_integrations_sweep_job(db)
        await ensure_memory_sweep_job(db)
        await ensure_integrations_rediscover_job(db)
        await ensure_refresh_webhooks_job(db)
        await log_job_concurrency_warnings(db)
        await db.commit()

    async def claim_and_execute_one() -> bool:
        job_id = await _claim_one_job(owner_instance_id=owner_id)
        if job_id is None:
            return False
        await _execute_claimed_job(job_id, owner_instance_id=owner_id)
        return True

    return await run_worker_batch(
        max_items=batch_size or settings.JOBS_WORKER_BATCH_SIZE,
        run_one=claim_and_execute_one,
        shutdown_event=shutdown_event,
    )


async def execute_claimed_job(job_id: UUID, *, owner_instance_id: str) -> None:
    """Execute one claimed job and finalize the attempt."""
    async with worker_run_slot():
        await _execute_claimed_job(job_id, owner_instance_id=owner_instance_id)


async def _execute_claimed_job(job_id: UUID, *, owner_instance_id: str) -> None:
    """Executes one claimed job after the caller reserves worker capacity."""
    maintenance_session_factory = get_maintenance_async_db_session_factory()
    async with maintenance_session_factory() as maintenance_db:
        claimed_job = await maintenance_db.scalar(
            select(Job).where(
                Job.id == job_id,
                Job.status == JOB_STATUS_RUNNING,
                Job.locked_by == owner_instance_id,
                Job.lock_expires_at.is_not(None),
                Job.lock_expires_at > datetime.now(UTC),
            )
        )
        if claimed_job is None:
            logger.warning(
                "Claimed job is no longer executable by this worker",
                extra={"job_id": str(job_id), "owner_instance_id": owner_instance_id},
            )
            return
        workspace_id = claimed_job.workspace_id
        user_id = claimed_job.concurrency_user_id

    heartbeat_stop = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None
    handler_task: asyncio.Task | None = None
    try:
        is_system_job = workspace_id is None and user_id is None
        session_factory = (
            get_maintenance_async_db_session_factory()
            if is_system_job
            else get_async_db_session_factory()
        )
        async with session_factory() as db:
            await configure_async_db_session(db)
            if not is_system_job:
                await set_session_tenant_context(
                    db,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
            now_utc = datetime.now(UTC)
            job = await db.scalar(
                select(Job).where(
                    Job.id == job_id,
                    Job.status == JOB_STATUS_RUNNING,
                    Job.locked_by == owner_instance_id,
                    Job.lock_expires_at.is_not(None),
                    Job.lock_expires_at > now_utc,
                )
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
                heartbeat_stop.set()
                finalized = await finalize_job_failure(
                    db,
                    job,
                    owner_instance_id=owner_instance_id,
                    code="unknown_kind",
                    message=f"No handler is registered for job kind '{job.kind}'",
                    force_terminal=True,
                )
                if finalized is None:
                    await db.rollback()
                    _log_stale_job_result(job_id, owner_instance_id=owner_instance_id)
                    return
                await db.commit()
                logger.error(
                    "Generic job failed because its handler is not registered",
                    extra={"job_id": str(job.id), "kind": job.kind},
                )
                return

            try:
                timeout_seconds = definition.timeout or settings.JOBS_HANDLER_TIMEOUT_SECONDS
                handler_task = asyncio.create_task(
                    definition.function(db, job),
                    name=f"generic-job-handler:{job_id}",
                )
                heartbeat_task = asyncio.create_task(
                    heartbeat_job_lease(
                        job_id=job_id,
                        owner_instance_id=owner_instance_id,
                        stop=heartbeat_stop,
                        lease_lost=lease_lost,
                        cancel_target=handler_task,
                    ),
                    name=f"generic-job-heartbeat:{job_id}",
                )
                await asyncio.wait_for(handler_task, timeout=timeout_seconds)
                heartbeat_stop.set()
                finalized = await finalize_job_success(
                    db,
                    job,
                    owner_instance_id=owner_instance_id,
                )
                if not finalized:
                    await db.rollback()
                    _log_stale_job_result(job_id, owner_instance_id=owner_instance_id)
                    return
                await db.commit()
                logger.info(
                    "Generic job completed",
                    extra={"job_id": str(job.id), "kind": job.kind},
                )
            except asyncio.CancelledError:
                heartbeat_stop.set()
                await db.rollback()
                current_task = asyncio.current_task()
                if not lease_lost.is_set() or (
                    current_task is not None and current_task.cancelling() > 0
                ):
                    raise
                _log_stale_job_result(job_id, owner_instance_id=owner_instance_id)
                return
            except TimeoutError:
                heartbeat_stop.set()
                await db.rollback()
                await _record_job_failure(
                    job_id,
                    owner_instance_id=owner_instance_id,
                    code="handler_timeout",
                    message=f"Job handler exceeded timeout for kind '{definition.kind}'",
                )
            except Exception as exc:
                heartbeat_stop.set()
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
    finally:
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        if handler_task is not None and not handler_task.done():
            handler_task.cancel()
            with suppress(asyncio.CancelledError):
                await handler_task


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


async def run_drain(
    *,
    shutdown_event: asyncio.Event,
    owner_instance_id: str | None = None,
) -> int:
    """Run generic-job passes without polling delays until no work remains."""
    owner_id = owner_instance_id or _owner_instance_id()
    total_claimed = 0
    while not shutdown_event.is_set():
        claimed_count = await run_once(
            owner_instance_id=owner_id,
            batch_size=settings.WORKER_MAX_CONCURRENT_RUNS,
            shutdown_event=shutdown_event,
        )
        total_claimed += claimed_count
        if shutdown_event.is_set():
            return total_claimed
        if claimed_count == 0:
            return total_claimed
        logger.info("Executed generic job batch", extra={"count": claimed_count})

    return total_claimed


async def _claim_one_job(*, owner_instance_id: str) -> UUID | None:
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        claimed = await claim_jobs(
            db,
            owner_instance_id=owner_instance_id,
            batch_size=1,
            lock_ttl_seconds=settings.JOBS_LOCK_TTL_SECONDS,
        )
        job_id = claimed[0].id if claimed else None
        await db.commit()
        return job_id


async def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the generic job runner."""
    parser = argparse.ArgumentParser(description="Run generic Praxis background jobs.")
    parser.add_argument("--once", action="store_true", help="Run one polling pass and exit.")
    args = parser.parse_args(argv)

    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    try:
        session_factory = get_maintenance_async_db_session_factory()
        async with session_factory() as db:
            await configure_async_db_session(db)
            await ensure_application_encryption_keys_loaded(db)
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
    session_factory = get_maintenance_async_db_session_factory()
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
            terminal = await finalize_job_failure(
                db,
                job,
                owner_instance_id=owner_instance_id,
                code=code,
                message=message,
            )
            if terminal is None:
                await db.rollback()
                _log_stale_job_result(job_id, owner_instance_id=owner_instance_id)
                return
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


def _log_stale_job_result(job_id: UUID, *, owner_instance_id: str) -> None:
    logger.warning(
        "Dropped generic job result because this worker no longer owns the lease",
        extra={"job_id": str(job_id), "owner_instance_id": owner_instance_id},
    )


async def _run_once_until_shutdown(
    *,
    shutdown_event: asyncio.Event,
    owner_instance_id: str,
    batch_size: int | None = None,
) -> int | None:
    pass_coro = (
        run_once(
            owner_instance_id=owner_instance_id,
            shutdown_event=shutdown_event,
        )
        if batch_size is None
        else run_once(
            owner_instance_id=owner_instance_id,
            batch_size=batch_size,
            shutdown_event=shutdown_event,
        )
    )
    polling_task = asyncio.create_task(
        pass_coro,
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

        timeout_seconds = settings.JOBS_WORKER_SHUTDOWN_SECONDS
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
