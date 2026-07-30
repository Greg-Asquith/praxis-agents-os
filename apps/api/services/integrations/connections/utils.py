# apps/api/services/integrations/connections/utils.py

"""Shared access, lookup, and response helpers for integration connections."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.integration import IntegrationAuthError, IntegrationNotFoundError
from models.integrations import ExternalCredential, IntegrationConnection, IntegrationDiscoveryRun
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.integrations.connections.schemas import (
    ConnectionRead,
    CredentialMetadataRead,
    DiscoveryRunRead,
)
from services.integrations.credentials import find_duplicate_principals
from services.integrations.domain import DISCOVER_RESOURCES_JOB_KIND
from services.integrations.oauth import refresh_authorization_token
from services.jobs.domain import IN_FLIGHT_JOB_STATUSES
from services.workspaces.utils import MANAGER_ROLES


async def get_visible_connection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    for_update: bool = False,
) -> IntegrationConnection:
    visibility = (IntegrationConnection.owner_workspace_id == workspace.id) | (
        IntegrationConnection.owner_user_id == actor.id
    )
    statement = select(IntegrationConnection).where(
        IntegrationConnection.id == connection_id,
        IntegrationConnection.deleted.is_(False),
        visibility,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    connection = await db.scalar(statement)
    if connection is None:
        raise IntegrationNotFoundError(
            "Integration connection not found",
            connection_id=str(connection_id),
            operation="get_connection",
        )
    return connection


def require_connection_mutation_allowed(
    connection: IntegrationConnection,
    *,
    actor: User,
    membership: WorkspaceMembership,
) -> None:
    is_manager = membership.role in MANAGER_ROLES
    if connection.owner_workspace_id is not None and not is_manager:
        raise AuthorizationError("Workspace integration changes require an administrator")
    if connection.owner_user_id is not None and connection.owner_user_id != actor.id:
        raise AuthorizationError("This integration connection belongs to another user")


async def refresh_oauth_credential(credential: ExternalCredential) -> dict[str, object]:
    """Refresh OAuth material and classify missing refresh state as reauthentication."""
    token = credential.refresh_token
    if not token:
        raise IntegrationAuthError(
            "Connection has no refresh token",
            provider_key=credential.provider_key,
            operation="refresh_connection",
        )
    return await refresh_authorization_token(
        provider_key=credential.provider_key,
        refresh_token=token,
    )


async def connection_to_read(
    db: AsyncSession,
    connection: IntegrationConnection,
    *,
    include_credential: bool,
    include_duplicates: bool = True,
) -> ConnectionRead:
    # Server-side timestamp updates expire attributes after flush; refresh in
    # the async context before constructing the synchronous response model.
    await db.refresh(connection)
    credential = await db.get(ExternalCredential, connection.credential_id)
    latest_discovery_runs = await latest_discovery_runs_for_connections(db, [connection.id])
    discovery_in_flight = await discovery_in_flight_connection_ids(db, [connection.id])
    duplicates: list[UUID] = []
    if credential is not None and include_duplicates and credential.revoked_at is None:
        duplicates = await find_duplicate_principals(
            db,
            provider_key=credential.provider_key,
            principal_fingerprint=credential.principal_fingerprint,
            owner_user_id=connection.owner_user_id,
            owner_workspace_id=connection.owner_workspace_id,
            exclude_credential_id=credential.id,
        )
    return build_connection_read(
        connection,
        credential,
        include_credential=include_credential,
        duplicates=duplicates,
        latest_discovery_run=latest_discovery_runs.get(connection.id),
        discovery_in_flight=connection.id in discovery_in_flight,
    )


async def latest_discovery_runs_for_connections(
    db: AsyncSession,
    connection_ids: list[UUID],
) -> dict[UUID, IntegrationDiscoveryRun]:
    if not connection_ids:
        return {}
    ranked_runs = (
        select(
            IntegrationDiscoveryRun.id.label("run_id"),
            func.row_number()
            .over(
                partition_by=IntegrationDiscoveryRun.connection_id,
                order_by=(
                    IntegrationDiscoveryRun.started_at.desc(),
                    IntegrationDiscoveryRun.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(IntegrationDiscoveryRun.connection_id.in_(connection_ids))
        .subquery()
    )
    runs = (
        await db.scalars(
            select(IntegrationDiscoveryRun)
            .join(ranked_runs, ranked_runs.c.run_id == IntegrationDiscoveryRun.id)
            .where(ranked_runs.c.position == 1)
        )
    ).all()
    return {run.connection_id: run for run in runs}


async def discovery_in_flight_connection_ids(
    db: AsyncSession,
    connection_ids: list[UUID],
) -> set[UUID]:
    """Return connections backed by pending or running discovery work."""
    if not connection_ids:
        return set()
    ids = await db.scalars(
        select(Job.subject_id).where(
            Job.kind == DISCOVER_RESOURCES_JOB_KIND,
            Job.subject_id.in_(connection_ids),
            Job.status.in_(IN_FLIGHT_JOB_STATUSES),
        )
    )
    return {connection_id for connection_id in ids if connection_id is not None}


def build_connection_read(
    connection: IntegrationConnection,
    credential: ExternalCredential | None,
    *,
    include_credential: bool,
    duplicates: list[UUID] | None = None,
    latest_discovery_run: IntegrationDiscoveryRun | None = None,
    discovery_in_flight: bool = False,
) -> ConnectionRead:
    metadata = None
    if credential is not None and include_credential:
        metadata = CredentialMetadataRead(
            auth_mode=credential.auth_mode,
            secret_reference=(
                f"{credential.secret_provider}:{credential.secret_name}#{credential.secret_version}"
                if credential.secret_provider
                and credential.secret_name
                and credential.secret_version
                else None
            ),
            token_expires_at=credential.token_expires_at,
            granted_scopes=credential.granted_scopes,
            principal_fingerprint=credential.principal_fingerprint,
            external_principal_label=credential.external_principal_label,
            last_refreshed_at=credential.last_refreshed_at,
            last_refresh_error_code=credential.last_refresh_error_code,
        )
    return ConnectionRead(
        id=connection.id,
        provider_key=connection.provider_key,
        label=connection.label,
        owner_scope="workspace" if connection.owner_workspace_id else "user",
        owner_user_id=connection.owner_user_id,
        owner_workspace_id=connection.owner_workspace_id,
        status=connection.status,
        status_reason=connection.status_reason,
        connected_by_user_id=connection.connected_by_user_id,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
        duplicate_of_connection_ids=duplicates or [],
        credential=metadata,
        discovery_in_flight=discovery_in_flight,
        latest_discovery_run=(
            DiscoveryRunRead(
                status=latest_discovery_run.status,
                resources_found=latest_discovery_run.resources_found,
                error_code=latest_discovery_run.error_code,
                started_at=latest_discovery_run.started_at,
                finished_at=latest_discovery_run.finished_at,
            )
            if latest_discovery_run is not None
            else None
        ),
    )
