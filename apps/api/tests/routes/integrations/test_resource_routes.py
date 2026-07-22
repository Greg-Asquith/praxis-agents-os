# apps/api/tests/routes/integrations/test_resource_routes.py

"""Resource discovery selection route coverage."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from models.integrations import IntegrationConnection, IntegrationResource
from models.workspace import WorkspaceRole
from services.integrations.manifest import (
    PROVIDER_MANIFESTS,
    IntegrationProviderManifest,
    register_provider_manifest,
)
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    IntegrationProviderPlugin,
    register_provider_plugin,
)
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_discovery_run,
    build_integration_resource,
)
from tests.routes.integrations.conftest import create_identity

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def discoverable_route_provider() -> Iterator[None]:
    async def discover_resources(_credential: str, _principal_label: str | None = None):
        return ()

    plugin = IntegrationProviderPlugin(
        manifest=IntegrationProviderManifest(
            provider_key="test_provider",
            display_name="Test Provider",
            auth_modes=("api_key",),
            owner_scope="workspace",
            resource_types=("test_resource",),
            requires_discovery=True,
            required_form_fields=("api_key",),
        ),
        discover_resources=discover_resources,
    )
    register_provider_plugin(plugin)
    register_provider_manifest(plugin.manifest)
    yield
    PROVIDER_PLUGINS.pop(plugin.manifest.provider_key, None)
    PROVIDER_MANIFESTS.pop(plugin.manifest.provider_key, None)


async def _connection_with_resources(
    db: AsyncSession,
    identity: dict[str, object],
    *,
    owner_scope: str = "workspace",
) -> tuple[IntegrationConnection, IntegrationResource, IntegrationResource]:
    credential = build_external_credential(
        auth_mode="api_key",
        access_token_encrypted=None,
        secret_provider="local_env",  # noqa: S106 - inert test metadata
        secret_name="route-secret",  # noqa: S106 - inert test metadata
        secret_version="latest",  # noqa: S106 - inert test metadata
    )
    connection = build_integration_connection(
        credential=credential,
        user=identity["user"],
        workspace=identity["workspace"] if owner_scope == "workspace" else None,
        owner_user_id=identity["user"].id if owner_scope == "user" else None,
        status="needs_resource_selection",
    )
    available = build_integration_resource(
        connection=connection,
        external_id="available",
        display_name="Available resource",
        writable=True,
        permissions_metadata={"role": "editor"},
    )
    removed = build_integration_resource(
        connection=connection,
        external_id="removed",
        display_name="Removed resource",
        availability="removed",
        removed_at=datetime.now(UTC),
        enabled=True,
    )
    discovery_run = build_integration_discovery_run(connection=connection)
    db.add_all([credential, connection, available, removed, discovery_run])
    await db.commit()
    return connection, available, removed


async def test_list_includes_provider_removed_resources_for_read_only_member(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection, available, removed = await _connection_with_resources(
        db_session, integration_identity
    )
    _reader, _workspace, _membership, headers = await create_identity(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=integration_identity["workspace"],
    )

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/resources",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    by_id = {row["id"]: row for row in response.json()}
    assert set(by_id) == {str(available.id), str(removed.id)}
    assert by_id[str(removed.id)]["availability"] == "removed"
    assert by_id[str(available.id)]["metadata"] == {"role": "editor"}


async def test_selection_replace_set_recomputes_status_and_audits_diff(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection, available, removed = await _connection_with_resources(
        db_session, integration_identity
    )
    _member, _workspace, _membership, headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=integration_identity["workspace"],
    )

    selected = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection.id}/resources/selection",
        headers=headers,
        json={"enabled_resource_ids": [str(available.id)]},
    )

    assert selected.status_code == 200, selected.text
    assert selected.json() == {
        "connection_id": str(connection.id),
        "enabled_resource_ids": [str(available.id)],
        "status": "active",
    }
    connection_id = connection.id
    available_id = available.id
    removed_id = removed.id
    db_session.expire_all()
    persisted_available = await db_session.get(IntegrationResource, available_id)
    persisted_removed = await db_session.get(IntegrationResource, removed_id)
    assert persisted_available is not None and persisted_available.enabled is True
    assert persisted_removed is not None and persisted_removed.enabled is False
    event = await db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.resource_type == "integration_resource",
            AuditEvent.resource_id == str(connection_id),
        )
        .order_by(AuditEvent.occurred_at.desc())
    )
    assert event is not None
    assert event.details == {
        "enabled_added": [str(available_id)],
        "enabled_removed": [str(removed_id)],
    }

    cleared = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection_id}/resources/selection",
        headers=headers,
        json={"enabled_resource_ids": []},
    )
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "needs_resource_selection"


async def test_selection_rejects_unknown_foreign_and_removed_resource_ids(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection, _available, removed = await _connection_with_resources(
        db_session, integration_identity
    )
    other_connection, foreign, _other_removed = await _connection_with_resources(
        db_session, integration_identity
    )
    assert other_connection.id != connection.id

    for resource_id in (uuid4(), foreign.id, removed.id):
        response = await db_async_client.put(
            f"/api/v1/integrations/connections/{connection.id}/resources/selection",
            headers=integration_identity["headers"],
            json={"enabled_resource_ids": [str(resource_id)]},
        )
        assert response.status_code == 400, response.text


async def test_resource_route_rbac_and_user_connection_owner_rule(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    workspace_connection, available, _removed = await _connection_with_resources(
        db_session, integration_identity
    )
    user_connection, user_resource, _user_removed = await _connection_with_resources(
        db_session,
        integration_identity,
        owner_scope="user",
    )
    _reader, _workspace, _membership, reader_headers = await create_identity(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=integration_identity["workspace"],
    )
    _member, _workspace, _membership, member_headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=integration_identity["workspace"],
    )

    forbidden = await db_async_client.put(
        f"/api/v1/integrations/connections/{workspace_connection.id}/resources/selection",
        headers=reader_headers,
        json={"enabled_resource_ids": [str(available.id)]},
    )
    assert forbidden.status_code == 403

    hidden_user_connection = await db_async_client.put(
        f"/api/v1/integrations/connections/{user_connection.id}/resources/selection",
        headers=member_headers,
        json={"enabled_resource_ids": [str(user_resource.id)]},
    )
    assert hidden_user_connection.status_code == 404


async def test_trigger_discovery_returns_202_and_deduplicates(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection, _available, _removed = await _connection_with_resources(
        db_session, integration_identity
    )

    first = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection.id}/discover",
        headers=integration_identity["headers"],
    )
    second = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection.id}/discover",
        headers=integration_identity["headers"],
    )

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert second.json()["job_id"] == first.json()["job_id"]
