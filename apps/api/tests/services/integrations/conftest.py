"""Suite-local discoverable provider fixtures."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from importlib import import_module
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from services.integrations.manifest import (
    PROVIDER_MANIFESTS,
    IntegrationProviderManifest,
    register_provider_manifest,
)
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    DiscoveredIntegrationResource,
    IntegrationProviderPlugin,
    register_provider_plugin,
)
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_user,
    build_workspace,
)


@pytest.fixture
def discovery_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, object]]:
    original_manifests = dict(PROVIDER_MANIFESTS)
    original_plugins = dict(PROVIDER_PLUGINS)
    state: dict[str, object] = {
        "calls": 0,
        "block": False,
        "error": None,
        "resources": [
            DiscoveredIntegrationResource(
                resource_type="test_resource",
                external_id="resource-1",
                display_name="Resource One",
                writable=True,
                permissions_metadata={"role": "editor"},
            )
        ],
    }

    async def discover_resources(credential: str):
        assert credential == "test-secret"
        state["calls"] = int(state["calls"]) + 1
        if state["block"]:
            await asyncio.Event().wait()
        error = state["error"]
        if isinstance(error, Exception):
            raise error
        return tuple(state["resources"])

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
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    register_provider_plugin(plugin)
    register_provider_manifest(plugin.manifest)

    async def resolve_test_secret(*args, **kwargs) -> str:
        return "test-secret"

    run_discovery_module = import_module("services.integrations.discovery.run_discovery")
    monkeypatch.setattr(run_discovery_module, "resolve_secret", resolve_test_secret)
    yield state
    PROVIDER_MANIFESTS.clear()
    PROVIDER_MANIFESTS.update(original_manifests)
    PROVIDER_PLUGINS.clear()
    PROVIDER_PLUGINS.update(original_plugins)


@pytest_asyncio.fixture
async def discovery_connection(
    db_session: AsyncSession,
    discovery_provider: dict[str, object],
) -> AsyncIterator[dict[str, object]]:
    unique_id = uuid4().hex
    user = build_user(email=f"discovery-{unique_id}@example.com")
    workspace = build_workspace(slug=f"discovery-{unique_id}")
    credential = build_external_credential(
        auth_mode="api_key",
        access_token_encrypted=None,
        secret_provider="local_env",  # noqa: S106 - inert test reference metadata
        secret_name="test-secret",  # noqa: S106 - inert test reference metadata
        secret_version="latest",  # noqa: S106 - inert test reference metadata
    )
    db_session.add_all([user, workspace, credential])
    await db_session.flush()
    connection = build_integration_connection(
        credential=credential,
        user=user,
        workspace=workspace,
        status="discovery_pending",
    )
    db_session.add(connection)
    await db_session.flush()
    yield {
        "user": user,
        "workspace": workspace,
        "credential": credential,
        "connection": connection,
        "provider": discovery_provider,
    }
