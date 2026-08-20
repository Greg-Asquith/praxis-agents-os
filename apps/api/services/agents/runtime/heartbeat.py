# apps/api/services/agents/runtime/heartbeat.py

"""Lease heartbeat helpers for detached agent turn workers."""

import asyncio
import logging
import os
from contextlib import suppress
from uuid import UUID

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    get_async_engine,
    set_session_tenant_context,
)
from core.settings import settings
from services.agent_runs import renew_agent_run_lease
from services.agent_runs.domain import RUN_STATUS_CANCELLED
from services.agents.runtime.cancellation import (
    read_agent_run_status_once,
    request_agent_run_task_cancel,
)

logger = logging.getLogger(__name__)


def agent_run_owner_instance_id() -> str:
    """Returns the process identity recorded on live agent-run leases."""
    return f"{os.uname().nodename}:{os.getpid()}"


def _runtime_pool_status() -> str:
    try:
        return get_async_engine().pool.status()
    except Exception:
        return "unavailable"


async def renew_agent_run_lease_once(
    *,
    run_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    owner_instance_id: str,
) -> bool:
    """Renew one run lease in an isolated short-lived transaction."""
    session_factory = get_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        await set_session_tenant_context(db, workspace_id=workspace_id, user_id=user_id)
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
    workspace_id: UUID,
    user_id: UUID,
    owner_instance_id: str,
    stop: asyncio.Event,
    cancel_target: asyncio.Task | None = None,
    renew_immediately: bool = False,
) -> None:
    """Renew a run lease until ``stop`` is set or the run is no longer live."""
    interval = settings.AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS
    while not stop.is_set():
        if not renew_immediately:
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
                break
        renew_immediately = False

        try:
            renewed = await renew_agent_run_lease_once(
                run_id=run_id,
                workspace_id=workspace_id,
                user_id=user_id,
                owner_instance_id=owner_instance_id,
            )
        except Exception:
            logger.error(
                "Failed to renew agent run lease",
                exc_info=True,
                extra={
                    "run_id": str(run_id),
                    "owner_instance_id": owner_instance_id,
                    "pool_status": _runtime_pool_status(),
                },
            )
            continue

        if not renewed:
            await cancel_target_if_run_cancelled(
                run_id=run_id,
                workspace_id=workspace_id,
                user_id=user_id,
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
    workspace_id: UUID,
    user_id: UUID,
    owner_instance_id: str,
    cancel_target: asyncio.Task | None,
) -> bool:
    """Cancel ``cancel_target`` after a failed renewal only when the row is cancelled."""
    if cancel_target is None or cancel_target.done() or cancel_target.cancelling() > 0:
        return False

    status = await read_agent_run_status_once(
        run_id=run_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if status != RUN_STATUS_CANCELLED:
        return False

    logger.info(
        "Cancelling agent run task after heartbeat observed cancellation",
        extra={"run_id": str(run_id), "owner_instance_id": owner_instance_id},
    )
    request_agent_run_task_cancel(cancel_target, run_id=run_id)
    return True
