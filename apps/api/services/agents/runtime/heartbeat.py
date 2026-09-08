# apps/api/services/agents/runtime/heartbeat.py

"""Lease heartbeat helpers for detached agent turn workers."""

import asyncio
import logging
from contextlib import suppress
from uuid import UUID, uuid4

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    get_async_engine,
    set_session_tenant_context,
)
from core.settings import settings
from services.agent_runs.renew_lease import renew_agent_run_lease
from services.agents.runtime.execution_control import (
    ExecutionControl,
    ExecutionInterruptedError,
    InterruptionReason,
)

logger = logging.getLogger(__name__)


def agent_run_owner_instance_id() -> str:
    """Returns an opaque identity for one admitted invocation."""
    return str(uuid4())


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
                workspace_id=workspace_id,
                user_id=user_id,
            )
            await db.commit()
            return renewed
        except Exception:
            await db.rollback()
            raise


async def heartbeat_agent_run_lease(
    *,
    execution_control: ExecutionControl,
    stop: asyncio.Event,
    cancel_target: asyncio.Task | None = None,
    renew_immediately: bool = False,
) -> None:
    """Renews the admitted owner until release or confirmed permission loss."""
    control = execution_control
    interval = settings.AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS
    while not stop.is_set():
        if not renew_immediately:
            remaining = max(0, control.lease_deadline - asyncio.get_running_loop().time())
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=min(interval, remaining))
                return
        renew_immediately = False
        try:
            renewed = await _renew_owned_lease(control)
        except Exception:
            logger.error(
                "Failed to renew agent run lease",
                exc_info=True,
                extra={
                    "run_id": str(control.run_id),
                    "owner_instance_id": control.owner_instance_id,
                    "pool_status": _runtime_pool_status(),
                },
            )
            if asyncio.get_running_loop().time() >= control.lease_deadline:
                _cancel_revoked_execution(control, InterruptionReason.LEASE_LOST, cancel_target)
                return
            continue
        try:
            if not renewed or control.root is not None:
                await control.check_permission()
        except ExecutionInterruptedError as exc:
            _cancel_revoked_execution(control, exc.reason, cancel_target)
            return
        if not renewed:
            return


async def _renew_owned_lease(control: ExecutionControl) -> bool:
    renewal_started = asyncio.get_running_loop().time()
    async with asyncio.timeout_at(control.lease_deadline):
        renewed = await renew_agent_run_lease_once(
            run_id=control.run_id,
            workspace_id=control.workspace_id,
            user_id=control.user_id,
            owner_instance_id=control.owner_instance_id,
        )
    if renewed:
        control.lease_deadline = renewal_started + settings.AGENT_RUN_LEASE_TTL_SECONDS
    return renewed


async def stop_agent_run_heartbeat(
    stop: asyncio.Event | None,
    task: asyncio.Task | None,
) -> None:
    """Stops and joins the ticker before handing off or releasing execution."""
    if stop is not None:
        stop.set()
    if task is not None:
        task.cancel()
        await asyncio.wait({task})
        if not task.cancelled():
            task.result()


def _cancel_revoked_execution(
    control: ExecutionControl,
    reason: InterruptionReason,
    target: asyncio.Task | None,
) -> None:
    control.interrupt(reason)
    if target is not None and not target.done() and not target.cancelling():
        target.cancel(control.reason.value)
