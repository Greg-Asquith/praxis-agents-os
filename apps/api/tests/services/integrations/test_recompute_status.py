"""Selection-driven connection status recomputation."""

from sqlalchemy.ext.asyncio import AsyncSession

from services.integrations.connections.recompute_connection_status import (
    recompute_connection_status,
)
from tests.factories import build_integration_discovery_run, build_integration_resource


async def test_recompute_status_tracks_enabled_live_resources(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    run = build_integration_discovery_run(connection=connection)
    resource = build_integration_resource(connection=connection)
    db_session.add_all([run, resource])
    await db_session.flush()

    assert await recompute_connection_status(db_session, connection) == "needs_resource_selection"
    resource.enabled = True
    assert await recompute_connection_status(db_session, connection) == "active"
    resource.enabled = False
    assert await recompute_connection_status(db_session, connection) == "needs_resource_selection"


async def test_recompute_does_not_overwrite_event_driven_statuses(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    db_session.add(build_integration_discovery_run(connection=connection))
    await db_session.flush()
    for status in ("degraded", "error", "needs_reauth", "needs_credential"):
        connection.status = status
        assert await recompute_connection_status(db_session, connection) == status
