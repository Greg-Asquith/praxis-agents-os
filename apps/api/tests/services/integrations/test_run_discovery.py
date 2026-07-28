"""Discovery reconciliation behavior."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationCredentialUnavailableError,
    IntegrationValidationError,
)
from models.integrations import IntegrationDiscoveryRun, IntegrationResource
from models.jobs import Job
from services.integrations.discovery import run_discovery
from services.integrations.plugin import PROVIDER_PLUGINS, DiscoveredIntegrationResource
from services.jobs.registry import JOB_HANDLERS, job_handler


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


async def test_successful_discovery_enqueues_one_provider_metadata_sync(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    kind = "tests.sync_provider_metadata"

    async def handler(_db, _job) -> None:
        return None

    job_handler(kind=kind)(handler)
    original = PROVIDER_PLUGINS[connection.provider_key]
    PROVIDER_PLUGINS[connection.provider_key] = replace(
        original,
        metadata_sync_job_kind=kind,
    )
    try:
        await run_discovery(db_session, connection_id=connection.id)
        await run_discovery(db_session, connection_id=connection.id)

        count = await db_session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.kind == kind,
                Job.subject_type == "integration_connection",
                Job.subject_id == connection.id,
            )
        )
        assert count == 1
    finally:
        JOB_HANDLERS.pop(kind, None)


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


async def test_reference_provider_auth_failure_requires_credential_replacement(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    connection = discovery_connection["connection"]
    provider = discovery_connection["provider"]
    provider["error"] = IntegrationAuthError(
        "Credential rejected",
        provider_key=connection.provider_key,
        operation="discover_resources",
    )

    with pytest.raises(IntegrationAuthError):
        await run_discovery(db_session, connection_id=connection.id)

    assert connection.status == "needs_credential"


async def test_oauth_provider_auth_failure_requires_sign_in(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = discovery_connection["connection"]
    credential = discovery_connection["credential"]
    provider = discovery_connection["provider"]
    credential.auth_mode = "oauth"
    credential.secret_provider = None
    credential.secret_name = None
    credential.secret_version = None
    credential.access_token_encrypted = "ciphertext"
    await db_session.flush()
    provider["error"] = IntegrationAuthError(
        "OAuth rejected",
        provider_key=connection.provider_key,
        operation="discover_resources",
    )

    async def resolve_oauth(*args, **kwargs):
        return "test-secret", frozenset(), None

    module = __import__(
        "services.integrations.discovery.run_discovery",
        fromlist=["_resolve_credential_value"],
    )
    monkeypatch.setattr(module, "_resolve_credential_value", resolve_oauth)

    with pytest.raises(IntegrationAuthError):
        await run_discovery(db_session, connection_id=connection.id)

    assert connection.status == "needs_reauth"


async def test_vault_unavailability_preserves_prior_success_and_recovers(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = discovery_connection["connection"]
    credential = discovery_connection["credential"]
    first = await run_discovery(db_session, connection_id=connection.id)
    resource = await db_session.scalar(
        select(IntegrationResource).where(IntegrationResource.connection_id == connection.id)
    )
    assert first.status == "succeeded"
    assert resource is not None
    resource.enabled = True
    connection.status = "active"

    module = __import__(
        "services.integrations.discovery.run_discovery",
        fromlist=["resolve_secret"],
    )

    async def unavailable(*args, **kwargs):
        raise IntegrationCredentialUnavailableError(
            "Credential unavailable",
            provider_key="local",
            operation="resolve_secret",
        )

    monkeypatch.setattr(module, "resolve_secret", unavailable)
    with pytest.raises(IntegrationCredentialUnavailableError):
        await run_discovery(db_session, connection_id=connection.id)

    await db_session.refresh(credential)
    await db_session.refresh(resource)
    assert connection.status == "degraded"
    assert credential.deleted is False
    assert resource.enabled is True
    assert resource.availability == "available"

    async def available(*args, **kwargs):
        return "test-secret"

    monkeypatch.setattr(module, "resolve_secret", available)
    recovered = await run_discovery(db_session, connection_id=connection.id)
    assert recovered.status == "succeeded"
    assert connection.status == "active"


async def test_runtime_registry_without_discovery_callable_is_defensively_rejected(
    db_session: AsyncSession,
    discovery_connection: dict[str, object],
) -> None:
    from services.integrations.plugin import IntegrationProviderPlugin

    connection = discovery_connection["connection"]
    plugin = PROVIDER_PLUGINS[connection.provider_key]
    PROVIDER_PLUGINS[connection.provider_key] = IntegrationProviderPlugin(
        manifest=plugin.manifest,
        discover_resources=None,
    )
    with pytest.raises(IntegrationValidationError, match="not implemented"):
        await run_discovery(db_session, connection_id=connection.id)
