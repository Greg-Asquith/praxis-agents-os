# apps/api/services/agents/runtime/heartbeat.py

"""Lease heartbeat helpers for detached agent turn workers."""

import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from core.database import configure_async_db_session, get_async_db_session_factory
from core.settings import settings
from models.agent_run import AgentRun
from services.agent_runs import renew_agent_run_lease
from services.agent_runs.domain import RUN_STATUS_CANCELLED
from services.agents.runtime.cancellation import request_agent_run_task_cancel

logger = logging.getLogger(__name__)


async def renew_agent_run_lease_once(
    *,
    run_id: UUID,
    owner_instance_id: str,
) -> bool:
    """Renew one run lease in an isolated short-lived transaction."""
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        try:
            renewed = await renew_agent_run_lease(
                db,
                run_id=run_id,
                owner_instance_id=owner_instance_id,
            )
            await db.commit()
            return renewed
        except Exception:
            await db.rollback()
            raise


async def heartbeat_agent_run_lease(
    *,
    run_id: UUID,
    owner_instance_id: str,
    stop: asyncio.Event,
    cancel_target: asyncio.Task | None = None,
) -> None:
    """Renew a run lease until ``stop`` is set or the run is no longer live."""
    interval = settings.AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS
    while not stop.is_set():
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
            break

        try:
            renewed = await renew_agent_run_lease_once(
                run_id=run_id,
                owner_instance_id=owner_instance_id,
            )
        except Exception:
            logger.warning(
                "Failed to renew agent run lease",
                exc_info=True,
                extra={"run_id": str(run_id), "owner_instance_id": owner_instance_id},
            )
            continue

        if not renewed:
            await cancel_target_if_run_cancelled(
                run_id=run_id,
                owner_instance_id=owner_instance_id,
                cancel_target=cancel_target,
            )
            logger.info(
                "Stopping agent run heartbeat because the run is no longer live",
                extra={"run_id": str(run_id), "owner_instance_id": owner_instance_id},
            )
            break


async def cancel_target_if_run_cancelled(
    *,
    run_id: UUID,
    owner_instance_id: str,
    cancel_target: asyncio.Task | None,
) -> bool:
    """Cancel ``cancel_target`` after a failed renewal only when the row is cancelled."""
    if cancel_target is None or cancel_target.done() or cancel_target.cancelling() > 0:
        return False

    status = await read_agent_run_status_once(run_id=run_id)
    if status != RUN_STATUS_CANCELLED:
        return False

    logger.info(
        "Cancelling agent run task after heartbeat observed cancellation",
        extra={"run_id": str(run_id), "owner_instance_id": owner_instance_id},
    )
    request_agent_run_task_cancel(cancel_target, run_id=run_id)
    return True


async def read_agent_run_status_once(*, run_id: UUID) -> str | None:
    """Read one run status in an isolated short-lived transaction."""
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        run = await db.get(AgentRun, run_id)
        await db.commit()
        if run is None or run.deleted:
            return None
        return str(run.status)
