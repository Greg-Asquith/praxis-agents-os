# apps/api/bin/application_encryption.py

"""Enqueue and wait for a manual application-encryption maintenance job."""

# ruff: noqa: T201

import argparse
import asyncio
import json
from collections.abc import Sequence
from uuid import uuid4

from sqlalchemy import select

from core.database import (
    close_db_connections,
    configure_async_db_session,
    get_maintenance_async_db_session_factory,
)
from models.jobs import Job
from services.jobs.domain import TERMINAL_JOB_STATUSES
from services.jobs.enqueue_job import enqueue_job
from services.runtime_catalogs import assemble_runtime_catalogs
from workers.job_runner import run_once


async def run(mode: str) -> int:
    """Enqueue the maintenance job, execute worker passes, and print its report."""
    assemble_runtime_catalogs()

    from services.jobs.handlers.converge_application_encryption import (
        APPLICATION_ENCRYPTION_JOB_KIND,
    )

    session_factory = get_maintenance_async_db_session_factory()
    async with session_factory() as db:
        await configure_async_db_session(db)
        job = await enqueue_job(
            db,
            kind=APPLICATION_ENCRYPTION_JOB_KIND,
            payload={"mode": mode},
            content_hash=f"manual-{uuid4().hex}",
            priority=0,
            max_attempts=1,
        )
        await db.commit()
        job_id = job.id

    while True:
        await run_once(batch_size=1)
        async with session_factory() as db:
            current = await db.scalar(select(Job).where(Job.id == job_id))
            if current is None:
                raise RuntimeError("Application encryption job disappeared")
            if current.status not in TERMINAL_JOB_STATUSES:
                await asyncio.sleep(0.5)
                continue
            print(json.dumps({"job_id": str(job_id), "status": current.status, **current.payload}))
            return 0 if current.status == "succeeded" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("converge", "check"))
    args = parser.parse_args(argv)
    return asyncio.run(_run_and_close(args.mode))


async def _run_and_close(mode: str) -> int:
    try:
        return await run(mode)
    finally:
        await close_db_connections()


if __name__ == "__main__":
    raise SystemExit(main())
