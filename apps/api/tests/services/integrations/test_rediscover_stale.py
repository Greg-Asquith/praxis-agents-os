"""Periodic stale resource re-discovery."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationDiscoveryRun
from models.jobs import Job
from services.integrations.discovery.enqueue_discovery import enqueue_discovery
from services.integrations.discovery.handlers import discover_resources
from services.integrations.discovery.rediscover_stale import rediscover_stale
from services.integrations.plugin import DiscoveredIntegrationResource
from tests.factories import build_integration_discovery_run, build_integration_resource


async def test_rediscovery_refreshes_stale_permission_metadata(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    provider = discovery_connection["provider"]
    connection.status = "active"
    run = build_integration_discovery_run(
        connection=connection,
        finished_at=datetime.now(UTC) - timedelta(days=2),
    )
    job = Job(
        kind="integrations.rediscover_stale",
        content_hash="rediscover-test",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    resource = build_integration_resource(connection=connection, writable=True)
    db_session.add_all([run, resource, job])
    await db_session.flush()
    provider["resources"] = [
        DiscoveredIntegrationResource(
            resource_type="test_resource",
            external_id="resource-1",
            display_name="Resource One",
            writable=False,
            permissions_metadata={"role": "viewer"},
        )
    ]

    await rediscover_stale(db_session, job=job)
    discovery_job = await db_session.scalar(
        select(Job).where(
            Job.kind == "integrations.discover_resources",
            Job.subject_id == connection.id,
        )
    )
    assert discovery_job is not None
    assert discovery_job.initiated_by_user_id is None
    assert connection.status == "discovery_pending"
    await discover_resources(db_session, discovery_job)
    await db_session.refresh(resource)
    assert resource.writable is False
    assert resource.permissions_metadata == {"role": "viewer"}


async def test_rediscovery_skips_fresh_connection(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    connection.status = "active"
    run = build_integration_discovery_run(connection=connection)
    job = Job(
        kind="integrations.rediscover_stale",
        content_hash="rediscover-skip-test",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    db_session.add_all([run, job])
    await db_session.flush()

    await rediscover_stale(db_session, job=job)
    discovery_job = await db_session.scalar(
        select(Job).where(
            Job.kind == "integrations.discover_resources",
            Job.subject_id == connection.id,
        )
    )
    assert discovery_job is None
    persisted_run = await db_session.get(IntegrationDiscoveryRun, run.id)
    assert persisted_run is not None


@pytest.mark.parametrize("status", ["needs_reauth", "revoked"])
async def test_rediscovery_skips_auth_blocked_connections(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
    status: str,
) -> None:
    connection = discovery_connection["connection"]
    connection.status = status
    run = build_integration_discovery_run(
        connection=connection,
        finished_at=datetime.now(UTC) - timedelta(days=2),
    )
    job = Job(
        kind="integrations.rediscover_stale",
        content_hash=f"rediscover-{status}-test",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    db_session.add_all([run, job])
    await db_session.flush()

    await rediscover_stale(db_session, job=job)

    count = await db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.kind == "integrations.discover_resources",
            Job.subject_id == connection.id,
        )
    )
    assert count == 0


async def test_rediscovery_does_not_duplicate_in_flight_discovery(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    existing = await enqueue_discovery(db_session, connection=connection)
    scan_job = Job(
        kind="integrations.rediscover_stale",
        content_hash="rediscover-in-flight-test",
        payload={},
        attempts=1,
        max_attempts=5,
    )
    db_session.add(scan_job)
    await db_session.flush()

    await rediscover_stale(db_session, job=scan_job)

    jobs = list(
        (
            await db_session.scalars(
                select(Job).where(
                    Job.kind == "integrations.discover_resources",
                    Job.subject_id == connection.id,
                )
            )
        ).all()
    )
    assert [row.id for row in jobs] == [existing.id]
