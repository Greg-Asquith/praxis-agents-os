# apps/api/services/agents/runtime/heartbeat.py

"""Lease heartbeat helpers for detached agent turn workers."""

import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from core.database import configure_async_db_session, get_async_db_session_factory
from core.settings import settings
from services.agent_runs import renew_agent_run_lease

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
            logger.info(
                "Stopping agent run heartbeat because the run is no longer live",
                extra={"run_id": str(run_id), "owner_instance_id": owner_instance_id},
            )
            break
