"""Discovery reconciliation behavior."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integrations import IntegrationDiscoveryRun, IntegrationResource
from services.integrations.discovery import run_discovery
from services.integrations.plugin import DiscoveredIntegrationResource


async def test_run_discovery_is_idempotent_and_persists_permissions(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    first = await run_discovery(db_session, connection_id=connection.id)
    rows = list(
        (
            await db_session.scalars(
                select(IntegrationResource).where(
                    IntegrationResource.connection_id == connection.id
                )
            )
        ).all()
    )
    assert first.resources_added == 1
    assert first.resources_unchanged == 0
    assert len(rows) == 1
    row_id = rows[0].id
    first_seen_at = rows[0].first_seen_at
    assert rows[0].writable is True
    assert rows[0].permissions_metadata == {"role": "editor"}
    assert connection.status == "needs_resource_selection"

    second = await run_discovery(db_session, connection_id=connection.id)
    await db_session.refresh(rows[0])
    assert second.resources_added == 0
    assert second.resources_unchanged == 1
    assert rows[0].id == row_id
    assert rows[0].first_seen_at == first_seen_at


async def test_run_discovery_removes_and_resurrects_without_losing_selection(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    provider = discovery_connection["provider"]
    await run_discovery(db_session, connection_id=connection.id)
    resource = await db_session.scalar(
        select(IntegrationResource).where(IntegrationResource.connection_id == connection.id)
    )
    assert resource is not None
    resource.enabled = True
    provider["resources"] = []

    removed_run = await run_discovery(db_session, connection_id=connection.id)
    assert removed_run.resources_removed == 1
    assert resource.availability == "removed"
    assert resource.removed_at is not None
    assert resource.enabled is True
    resource.deleted = True
    resource.deleted_at = datetime.now(UTC)

    provider["resources"] = [
        DiscoveredIntegrationResource(
            resource_type="test_resource",
            external_id="resource-1",
            display_name="Renamed resource",
        )
    ]
    await run_discovery(db_session, connection_id=connection.id)
    assert resource.availability == "available"
    assert resource.deleted is False
    assert resource.deleted_at is None
    assert resource.removed_at is None
    assert resource.display_name == "Renamed resource"
    assert resource.enabled is True


async def test_provider_failure_persists_and_retry_keeps_credential(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    credential = discovery_connection["credential"]
    provider = discovery_connection["provider"]
    provider["error"] = RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await run_discovery(db_session, connection_id=connection.id)
    await db_session.refresh(connection)
    await db_session.refresh(credential)
    assert connection.status == "error"
    assert credential.deleted is False
    failed = await db_session.scalar(
        select(IntegrationDiscoveryRun).where(
            IntegrationDiscoveryRun.connection_id == connection.id,
            IntegrationDiscoveryRun.status == "failed",
        )
    )
    assert failed is not None
    assert failed.error_message == "provider unavailable"

    provider["error"] = None
    succeeded = await run_discovery(db_session, connection_id=connection.id)
    assert succeeded.status == "succeeded"
    assert connection.status == "needs_resource_selection"


async def test_runtime_registry_without_discovery_callable_is_defensively_rejected(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    from services.integrations.plugin import PROVIDER_PLUGINS, IntegrationProviderPlugin

    connection = discovery_connection["connection"]
    plugin = PROVIDER_PLUGINS[connection.provider_key]
    PROVIDER_PLUGINS[connection.provider_key] = IntegrationProviderPlugin(
        manifest=plugin.manifest,
        discover_resources=None,
    )
    with pytest.raises(IntegrationValidationError, match="not implemented"):
        await run_discovery(db_session, connection_id=connection.id)
