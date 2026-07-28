# apps/api/services/integrations/discovery/run_discovery.py

"""Discover and reconcile provider resources for one connection."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationNotFoundError,
    IntegrationValidationError,
)
from models.integrations import (
    ExternalCredential,
    IntegrationConnection,
    IntegrationDiscoveryRun,
    IntegrationResource,
)
from services.audit_events import AuditAction, AuditResourceType, AuditStatus
from services.integrations.connections.recompute_connection_status import (
    recompute_connection_status,
)
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.credentials import ensure_fresh_credential
from services.integrations.domain import (
    CONNECTION_STATUS_AUTH_PENDING,
    CONNECTION_STATUS_DISCOVERY_PENDING,
    CONNECTION_STATUS_NEEDS_CREDENTIAL,
    CONNECTION_STATUS_NEEDS_REAUTH,
    CONNECTION_STATUS_REVOKED,
)
from services.integrations.enqueue_metadata_sync import enqueue_metadata_sync
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.plugin import PROVIDER_PLUGINS, DiscoveredIntegrationResource
from services.integrations.utils import record_integration_audit
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference

MAX_ERROR_MESSAGE_LENGTH = 1000


async def run_discovery(
    db: AsyncSession,
    *,
    connection_id: UUID,
    job_id: UUID | None = None,
) -> IntegrationDiscoveryRun:
    """Run provider discovery and idempotently reconcile the local resource mirror."""
    connection = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.deleted.is_(False),
        )
    )
    if connection is None:
        raise IntegrationNotFoundError(
            "Integration connection not found",
            connection_id=str(connection_id),
            operation="discover_resources",
        )
    if connection.status == CONNECTION_STATUS_REVOKED:
        raise IntegrationConnectionError(
            "Revoked connections cannot discover resources",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="discover_resources",
        )
    if connection.status in {
        CONNECTION_STATUS_AUTH_PENDING,
        CONNECTION_STATUS_NEEDS_REAUTH,
        CONNECTION_STATUS_NEEDS_CREDENTIAL,
    }:
        raise IntegrationConnectionError(
            "Connection authentication must complete before resource discovery",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="discover_resources",
        )

    manifest = PROVIDER_MANIFESTS.get(connection.provider_key)
    if manifest is None:
        raise IntegrationValidationError(
            "Integration provider is not enabled",
            provider_key=connection.provider_key,
            operation="discover_resources",
        )
    if manifest.requires_discovery and connection.status != CONNECTION_STATUS_DISCOVERY_PENDING:
        await transition_connection_status(
            db,
            connection,
            CONNECTION_STATUS_DISCOVERY_PENDING,
            reason="resource_discovery_started",
        )

    now = datetime.now(UTC)
    discovery_run = IntegrationDiscoveryRun(
        connection_id=connection.id,
        job_id=job_id,
        status="running",
        started_at=now,
    )
    db.add(discovery_run)
    await db.flush()

    prior_success = await db.scalar(
        select(IntegrationDiscoveryRun.id)
        .where(
            IntegrationDiscoveryRun.connection_id == connection.id,
            IntegrationDiscoveryRun.id != discovery_run.id,
            IntegrationDiscoveryRun.status == "succeeded",
        )
        .limit(1)
    )

    try:
        credential_value, granted_scopes, principal_label = await _resolve_credential_value(
            db, connection
        )
        resources = await _fetch_resources(
            provider_key=connection.provider_key,
            credential_value=credential_value,
            principal_label=principal_label,
        )
        resources = _apply_granted_scope_permissions(resources, granted_scopes=granted_scopes)
        counters = await _reconcile_resources(
            db,
            connection=connection,
            resources=resources,
            now=now,
        )
        discovery_run.status = "succeeded"
        discovery_run.finished_at = datetime.now(UTC)
        discovery_run.resources_found = len(resources)
        discovery_run.resources_added = counters["added"]
        discovery_run.resources_removed = counters["removed"]
        discovery_run.resources_unchanged = counters["unchanged"]
        await recompute_connection_status(db, connection)
        await record_integration_audit(
            db,
            workspace_id=connection.owner_workspace_id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.INTEGRATION_RESOURCE,
            resource_id=connection.id,
            details={"provider_key": connection.provider_key, **counters},
        )
        await enqueue_metadata_sync(db, connection=connection)
        await db.flush()
        return discovery_run
    except IntegrationAuthError as exc:
        await db.refresh(connection)
        auth_mode = await db.scalar(
            select(ExternalCredential.auth_mode).where(
                ExternalCredential.id == connection.credential_id,
                ExternalCredential.deleted.is_(False),
            )
        )
        target = (
            CONNECTION_STATUS_NEEDS_REAUTH
            if auth_mode == "oauth"
            else CONNECTION_STATUS_NEEDS_CREDENTIAL
        )
        if connection.status != target:
            await transition_connection_status(
                db,
                connection,
                target,
                reason="resource_discovery_auth_failed",
                audit_status=AuditStatus.FAILURE,
            )
        await _persist_failure(db, discovery_run, exc, error_code="auth")
        raise
    except Exception as exc:
        target = "degraded" if prior_success is not None else "error"
        await transition_connection_status(
            db,
            connection,
            target,
            reason="resource_discovery_failed",
            audit_status=AuditStatus.FAILURE,
        )
        await _persist_failure(db, discovery_run, exc)
        raise


async def _resolve_credential_value(
    db: AsyncSession,
    connection: IntegrationConnection,
) -> tuple[str, frozenset[str], str | None]:
    credential = await db.get(ExternalCredential, connection.credential_id)
    if credential is None or credential.deleted:
        raise IntegrationNotFoundError(
            "Integration credential not found",
            provider_key=connection.provider_key,
            operation="discover_resources",
        )
    if credential.auth_mode == "oauth":
        fresh = await ensure_fresh_credential(
            db,
            credential_id=credential.id,
            refresh_token=refresh_oauth_credential,
        )
        access_token = fresh.access_token
        if not access_token:
            raise IntegrationAuthError(
                "Connection has no access token",
                provider_key=connection.provider_key,
                operation="discover_resources",
            )
        return (
            access_token,
            frozenset(fresh.granted_scopes or ()),
            fresh.external_principal_label,
        )
    return (
        await resolve_secret(
            db,
            SecretReference(
                provider=credential.secret_provider or "",
                name=credential.secret_name or "",
                version=credential.secret_version or "",
            ),
            workspace_id=connection.owner_workspace_id,
            actor_id=connection.connected_by_user_id,
        ),
        frozenset(),
        credential.external_principal_label,
    )


async def _fetch_resources(
    *,
    provider_key: str,
    credential_value: str,
    principal_label: str | None,
) -> tuple[DiscoveredIntegrationResource, ...]:
    plugin = PROVIDER_PLUGINS.get(provider_key)
    if plugin is None or plugin.discover_resources is None:
        raise IntegrationValidationError(
            "Provider discovery not implemented",
            provider_key=provider_key,
            operation="discover_resources",
        )
    resources = tuple(await plugin.discover_resources(credential_value, principal_label))
    manifest = plugin.manifest
    keys: set[tuple[str, str]] = set()
    for resource in resources:
        key = (resource.resource_type, resource.external_id)
        if resource.resource_type not in manifest.resource_types:
            raise IntegrationValidationError(
                "Provider returned an undeclared resource type",
                provider_key=provider_key,
                operation="discover_resources",
            )
        if not resource.external_id.strip() or not resource.display_name.strip() or key in keys:
            raise IntegrationValidationError(
                "Provider returned an invalid or duplicate resource",
                provider_key=provider_key,
                operation="discover_resources",
            )
        keys.add(key)
    return resources


def _apply_granted_scope_permissions(
    resources: tuple[DiscoveredIntegrationResource, ...],
    *,
    granted_scopes: frozenset[str],
) -> tuple[DiscoveredIntegrationResource, ...]:
    """Fail closed when a resource's write capability requires OAuth scopes."""
    return tuple(
        DiscoveredIntegrationResource(
            resource_type=item.resource_type,
            external_id=item.external_id,
            display_name=item.display_name,
            parent_external_id=item.parent_external_id,
            writable=item.writable and set(item.required_write_scopes).issubset(granted_scopes),
            required_write_scopes=item.required_write_scopes,
            permissions_metadata=item.permissions_metadata,
        )
        for item in resources
    )


async def _reconcile_resources(
    db: AsyncSession,
    *,
    connection: IntegrationConnection,
    resources: tuple[DiscoveredIntegrationResource, ...],
    now: datetime,
) -> dict[str, int]:
    existing = list(
        (
            await db.scalars(
                select(IntegrationResource).where(
                    IntegrationResource.connection_id == connection.id,
                )
            )
        ).all()
    )
    by_key = {(row.resource_type, row.external_id): row for row in existing}
    seen: set[tuple[str, str]] = set()
    added = 0
    unchanged = 0
    for item in resources:
        key = (item.resource_type, item.external_id)
        seen.add(key)
        row = by_key.get(key)
        if row is None:
            db.add(
                IntegrationResource(
                    connection_id=connection.id,
                    resource_type=item.resource_type,
                    external_id=item.external_id,
                    display_name=item.display_name,
                    parent_external_id=item.parent_external_id,
                    availability="available",
                    writable=item.writable,
                    permissions_metadata=item.permissions_metadata or {},
                    first_seen_at=now,
                    last_seen_at=now,
                )
            )
            added += 1
            continue
        row.display_name = item.display_name
        row.parent_external_id = item.parent_external_id
        row.deleted = False
        row.deleted_at = None
        row.deleted_by = None
        row.availability = "available"
        row.writable = item.writable
        row.permissions_metadata = item.permissions_metadata or {}
        row.last_seen_at = now
        row.removed_at = None
        unchanged += 1

    removed = 0
    for key, row in by_key.items():
        if key in seen or row.deleted or row.availability == "removed":
            continue
        row.availability = "removed"
        row.removed_at = now
        removed += 1
    return {"added": added, "removed": removed, "unchanged": unchanged}


async def _persist_failure(
    db: AsyncSession,
    discovery_run: IntegrationDiscoveryRun,
    exc: Exception,
    *,
    error_code: str | None = None,
) -> None:
    discovery_run.status = "failed"
    discovery_run.finished_at = datetime.now(UTC)
    discovery_run.error_code = (error_code or exc.__class__.__name__)[:64]
    discovery_run.error_message = _sanitize_error_message(str(exc) or exc.__class__.__name__)
    await db.commit()


def _sanitize_error_message(message: str) -> str:
    return " ".join(message.split())[:MAX_ERROR_MESSAGE_LENGTH]
