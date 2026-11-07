# apps/api/services/jobs/heartbeat_job_lease.py

"""Keep generic background job leases live during execution."""

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

from core.database import (
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
    lease_token: UUID,
    lease_expires_at: datetime,
    stop: asyncio.Event,
    lease_lost: asyncio.Event | None = None,
    cancel_target: asyncio.Task | None = None,
    interval_seconds: float | None = None,
    lock_ttl_seconds: float | None = None,
) -> None:
    """Renews a job lease and cancels the handler once the lease is lost or lapses."""
    ttl_seconds = (
        float(settings.JOBS_LOCK_TTL_SECONDS) if lock_ttl_seconds is None else lock_ttl_seconds
    )
    interval = interval_seconds if interval_seconds is not None else ttl_seconds / 3
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (lease_expires_at - datetime.now(UTC)).total_seconds()
    log_extra = {"job_id": str(job_id), "lease_token": str(lease_token)}
    while not stop.is_set():
        with suppress(TimeoutError):
            await asyncio.wait_for(
                stop.wait(), timeout=min(interval, max(0.0, deadline - loop.time()))
            )
            break

        renewal_started = loop.time()
        try:
            async with asyncio.timeout_at(deadline):
                renewed = await _renew_once(job_id, lease_token, ttl_seconds)
        except Exception:
            logger.error(
                "Failed to renew generic job lease",
                exc_info=True,
                extra={**log_extra, "pool_status": _maintenance_pool_status()},
            )
            if loop.time() < deadline:
                continue
            renewed = False

        if stop.is_set():
            break
        if renewed:
            deadline = renewal_started + ttl_seconds
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
            "Stopping generic job execution because its lease is no longer held",
            extra=log_extra,
        )
        break


async def _renew_once(job_id: UUID, lease_token: UUID, ttl_seconds: float) -> bool:
    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        renewed = await renew_job_lease(
            db,
            job_id=job_id,
            lease_token=lease_token,
            lock_ttl_seconds=ttl_seconds,
        )
        await db.commit()
        return renewed
