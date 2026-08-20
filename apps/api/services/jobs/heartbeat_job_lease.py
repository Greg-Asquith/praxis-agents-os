# apps/api/services/jobs/heartbeat_job_lease.py

"""Keep generic background job leases live during execution."""

import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from core.database import (
    configure_async_db_session,
    get_maintenance_async_db_session_factory,
    get_maintenance_async_engine,
)
from core.settings import settings
from services.jobs.renew_job_lease import renew_job_lease

logger = logging.getLogger(__name__)


def _maintenance_pool_status() -> str:
    try:
        return get_maintenance_async_engine().pool.status()
    except Exception:
        return "unavailable"


async def heartbeat_job_lease(
    *,
    job_id: UUID,
    owner_instance_id: str,
    stop: asyncio.Event,
    lease_lost: asyncio.Event | None = None,
    cancel_target: asyncio.Task | None = None,
    interval_seconds: float | None = None,
    lock_ttl_seconds: float | None = None,
) -> None:
    """Renews a job lease and cancels active work after confirmed ownership loss."""
    ttl_seconds = (
        float(settings.JOBS_LOCK_TTL_SECONDS) if lock_ttl_seconds is None else lock_ttl_seconds
    )
    interval = interval_seconds if interval_seconds is not None else ttl_seconds / 3
    while not stop.is_set():
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
            break

        session_factory = get_maintenance_async_db_session_factory()
        try:
            async with session_factory() as db:
                await configure_async_db_session(db)
                renewed = await renew_job_lease(
                    db,
                    job_id=job_id,
                    owner_instance_id=owner_instance_id,
                    lock_ttl_seconds=ttl_seconds,
                )
                await db.commit()
        except Exception:
            logger.error(
                "Failed to renew generic job lease",
                exc_info=True,
                extra={
                    "job_id": str(job_id),
                    "owner_instance_id": owner_instance_id,
                    "pool_status": _maintenance_pool_status(),
                },
            )
            continue

        if stop.is_set():
            break
        if renewed:
            continue
        if lease_lost is not None:
            lease_lost.set()
        if (
            cancel_target is not None
            and not cancel_target.done()
            and cancel_target.cancelling() == 0
        ):
            cancel_target.cancel()
        logger.warning(
            "Stopping generic job execution because its lease is no longer owned",
            extra={"job_id": str(job_id), "owner_instance_id": owner_instance_id},
        )
        break
