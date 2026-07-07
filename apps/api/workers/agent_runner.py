# apps/api/workers/agent_runner.py

"""Scheduled agent runner process."""

import argparse
import asyncio
import logging
import os
import signal
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from pydantic_ai.models import Model
from sqlalchemy import select

from core.database import (
    close_db_connections,
    configure_async_db_session,
    get_async_db_session_factory,
)
from core.exceptions.general import ConflictError
from core.logging import setup_logging
from core.observability import setup_agent_tracing
from core.settings import settings
from models.agent import AgentSchedule, AgentScheduleRun
from services.agent_runs.domain import RUN_STATUS_PENDING
from services.agent_schedules.finalize_schedule_run_execution import (
    finalize_schedule_run_execution,
)
from services.agent_schedules.prepare_schedule_run_execution import (
    PreparedScheduleRunExecution,
    prepare_schedule_run_execution,
)
from services.agent_schedules.reconcile_schedule_run_execution import (
    reconcile_schedule_run_execution,
)
from services.agent_schedules.runs import (
    claim_due_schedule_runs,
    mark_run_retryable_failure,
    mark_run_terminal_failure_and_disable_schedule,
)
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.heartbeat import heartbeat_agent_run_lease
from services.agents.runtime.sinks import NullSink

setup_logging()
setup_agent_tracing()
logger = logging.getLogger(__name__)


async def run_once(
    *,
    owner_instance_id: str | None = None,
    model: Model | None = None,
) -> int:
    """Reconcile stale work, claim due schedules, and execute one claimed batch."""
    owner_id = owner_instance_id or _owner_instance_id()
    session_factory = get_async_db_session_factory()

    async with session_factory() as db:
        await configure_async_db_session(db)
        reconciled = await reconcile_schedule_run_execution(db)
        if reconciled:
            logger.info("Reconciled scheduled agent runs", extra={"count": reconciled})
        claimed = await claim_due_schedule_runs(
            db,
            batch_size=settings.AGENT_SCHEDULE_WORKER_BATCH_SIZE,
            claim_ttl_seconds=settings.AGENT_SCHEDULE_RUN_CLAIM_TTL_SECONDS,
        )
        schedule_run_ids = [claimed_run.run.id for claimed_run in claimed]
        await db.commit()

    for schedule_run_id in schedule_run_ids:
        await execute_claimed_schedule_run(
            schedule_run_id=schedule_run_id,
            owner_instance_id=owner_id,
            model=model,
        )

    return len(schedule_run_ids)


async def execute_claimed_schedule_run(
    *,
    schedule_run_id: UUID,
    owner_instance_id: str,
    model: Model | None = None,
) -> None:
    """Prepare, execute, and finalize one claimed schedule run."""
    prepared = await _prepare(schedule_run_id)
    if prepared is None or not prepared.should_execute:
        return

    conversation_id, agent_run_id, _user_prompt = _execution_values(prepared)

    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        heartbeat_agent_run_lease(
            run_id=agent_run_id,
            owner_instance_id=owner_instance_id,
            stop=heartbeat_stop,
        ),
        name=f"scheduled-agent-run-heartbeat:{agent_run_id}",
    )

    try:
        await _execute_prepared(prepared, owner_instance_id=owner_instance_id, model=model)
    except Exception:
        logger.exception(
            "Scheduled agent run execution failed",
            extra={
                "schedule_id": str(prepared.schedule_id),
                "schedule_run_id": str(prepared.schedule_run_id),
                "agent_run_id": str(agent_run_id),
                "conversation_id": str(conversation_id),
            },
        )
    finally:
        heartbeat_stop.set()
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task

    await _finalize(prepared)


async def run_forever(
    *,
    shutdown_event: asyncio.Event,
    owner_instance_id: str | None = None,
) -> None:
    """Poll for scheduled runs until shutdown is requested."""
    owner_id = owner_instance_id or _owner_instance_id()
    while not shutdown_event.is_set():
        try:
            claimed_count = await _run_once_until_shutdown(
                shutdown_event=shutdown_event,
                owner_instance_id=owner_id,
            )
            if claimed_count:
                logger.info("Executed scheduled agent run batch", extra={"count": claimed_count})
        except Exception:
            logger.exception("Scheduled agent runner polling pass failed")

        if shutdown_event.is_set():
            break

        with suppress(TimeoutError):
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=settings.AGENT_SCHEDULE_WORKER_POLL_SECONDS,
            )


async def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for the scheduled agent runner."""
    parser = argparse.ArgumentParser(description="Run scheduled Praxis agents.")
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


async def _run_once_until_shutdown(
    *,
    shutdown_event: asyncio.Event,
    owner_instance_id: str,
) -> int | None:
    polling_task = asyncio.create_task(
        run_once(owner_instance_id=owner_instance_id),
        name="scheduled-agent-runner-pass",
    )
    shutdown_task = asyncio.create_task(
        shutdown_event.wait(),
        name="scheduled-agent-runner-shutdown-wait",
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
            "Shutdown requested; waiting for scheduled agent runner pass",
            extra={"timeout_seconds": timeout_seconds},
        )
        try:
            return await asyncio.wait_for(polling_task, timeout=timeout_seconds)
        except TimeoutError:
            logger.warning(
                "Scheduled agent runner pass exceeded shutdown timeout; cancelling",
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


async def _prepare(schedule_run_id: UUID) -> PreparedScheduleRunExecution | None:
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        try:
            prepared = await prepare_schedule_run_execution(
                db,
                schedule_run_id=schedule_run_id,
            )
            await db.commit()
            if prepared.should_execute:
                logger.info(
                    "Prepared scheduled agent run",
                    extra={
                        "schedule_id": str(prepared.schedule_id),
                        "schedule_run_id": str(prepared.schedule_run_id),
                        "agent_run_id": str(prepared.agent_run_id),
                        "conversation_id": str(prepared.conversation_id),
                    },
                )
            return prepared
        except Exception as exc:
            await db.rollback()
            await _record_claim_setup_failure(schedule_run_id, exc)
            return None


async def _execute_prepared(
    prepared: PreparedScheduleRunExecution,
    *,
    owner_instance_id: str,
    model: Model | None,
) -> None:
    conversation_id, agent_run_id, user_prompt = _execution_values(prepared)

    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        try:
            await execute_run(
                db,
                conversation_id=conversation_id,
                run_id=agent_run_id,
                user_prompt=user_prompt,
                sink=NullSink(
                    run_id=agent_run_id,
                    conversation_id=conversation_id,
                ),
                model=model,
                owner_instance_id=owner_instance_id,
                expected_status=RUN_STATUS_PENDING,
            )
        except Exception:
            await db.rollback()
            raise


async def _finalize(prepared: PreparedScheduleRunExecution) -> None:
    _conversation_id, agent_run_id, _user_prompt = _execution_values(prepared)

    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        try:
            await finalize_schedule_run_execution(
                db,
                schedule_run_id=prepared.schedule_run_id,
                agent_run_id=agent_run_id,
            )
            await db.commit()
        except ConflictError:
            await db.rollback()
            logger.warning(
                "Scheduled agent run could not be finalized yet",
                exc_info=True,
                extra={
                    "schedule_id": str(prepared.schedule_id),
                    "schedule_run_id": str(prepared.schedule_run_id),
                    "agent_run_id": str(agent_run_id),
                    "conversation_id": str(prepared.conversation_id),
                },
            )
        except Exception:
            await db.rollback()
            logger.exception(
                "Scheduled agent run finalization failed",
                extra={
                    "schedule_id": str(prepared.schedule_id),
                    "schedule_run_id": str(prepared.schedule_run_id),
                    "agent_run_id": str(agent_run_id),
                    "conversation_id": str(prepared.conversation_id),
                },
            )


async def _record_claim_setup_failure(schedule_run_id: UUID, exc: Exception) -> None:
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        try:
            schedule_run = await db.scalar(
                select(AgentScheduleRun)
                .where(
                    AgentScheduleRun.id == schedule_run_id,
                    AgentScheduleRun.deleted == False,  # noqa: E712
                )
                .with_for_update()
            )
            if schedule_run is None:
                await db.rollback()
                return
            schedule = await db.scalar(
                select(AgentSchedule)
                .where(
                    AgentSchedule.id == schedule_run.schedule_id,
                    AgentSchedule.deleted == False,  # noqa: E712
                )
                .with_for_update()
            )
            if schedule is None:
                await db.rollback()
                return

            code = exc.__class__.__name__
            message = str(exc) or code
            now = datetime.now(UTC)
            exhausted = mark_run_retryable_failure(
                schedule_run,
                now=now,
                code=code,
                message=message,
                max_attempts=settings.AGENT_SCHEDULE_RUN_MAX_ATTEMPTS,
            )
            if exhausted:
                await mark_run_terminal_failure_and_disable_schedule(
                    db,
                    schedule,
                    schedule_run,
                    now=now,
                    code=code,
                    message=message,
                )
            await db.commit()
            logger.warning(
                "Scheduled agent run setup failed",
                exc_info=True,
                extra={
                    "schedule_id": str(schedule.id),
                    "schedule_run_id": str(schedule_run.id),
                    "status": schedule_run.status,
                },
            )
        except Exception:
            await db.rollback()
            logger.exception(
                "Failed to record scheduled run setup failure",
                extra={"schedule_run_id": str(schedule_run_id)},
            )


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, shutdown_event.set)


def _owner_instance_id() -> str:
    return f"{os.uname().nodename}:{os.getpid()}"


def _execution_values(prepared: PreparedScheduleRunExecution) -> tuple[UUID, UUID, str]:
    if (
        prepared.conversation_id is None
        or prepared.agent_run_id is None
        or prepared.user_prompt is None
    ):
        raise RuntimeError("Prepared schedule run is missing execution values")
    return prepared.conversation_id, prepared.agent_run_id, prepared.user_prompt


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
