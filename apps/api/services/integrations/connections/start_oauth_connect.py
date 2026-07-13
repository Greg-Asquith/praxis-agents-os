# apps/api/services/integrations/connections/start_oauth_connect.py

"""Create or restart a labelled OAuth integration connection."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.integration import IntegrationConnectionError, IntegrationValidationError
from models.integrations import ExternalCredential, IntegrationConnection, IntegrationOAuthState
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.schemas import OAuthConnectRequest, OAuthConnectResponse
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.connections.utils import (
    get_visible_connection,
    require_connection_mutation_allowed,
)
from services.integrations.domain import (
    CONNECTION_STATUS_AUTH_PENDING,
    CONNECTION_STATUS_NEEDS_REAUTH,
)
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.oauth import build_authorization_url
from services.integrations.oauth.utils import (
    create_integration_oauth_state,
    encrypt_code_verifier,
    generate_code_verifier,
)
from services.integrations.providers_view import is_provider_configured
from services.integrations.utils import record_integration_audit
from services.workspaces.utils import MANAGER_ROLES


async def start_oauth_connect(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: OAuthConnectRequest,
) -> OAuthConnectResponse:
    manifest = PROVIDER_MANIFESTS.get(payload.provider_key)
    if manifest is None or "oauth" not in manifest.auth_modes:
        raise IntegrationValidationError(
            "OAuth provider is not enabled",
            provider_key=payload.provider_key,
            operation="start_oauth_connect",
        )
    if not is_provider_configured(manifest):
        raise IntegrationValidationError(
            "OAuth provider is not configured",
            provider_key=payload.provider_key,
            operation="start_oauth_connect",
        )
    if payload.owner_scope != manifest.owner_scope:
        raise IntegrationValidationError(
            "Connection owner scope does not match the provider",
            provider_key=payload.provider_key,
            operation="start_oauth_connect",
        )
    if manifest.owner_scope == "workspace" and membership.role not in MANAGER_ROLES:
        raise AuthorizationError("Workspace integrations require an administrator")

    label = payload.label.strip()
    if not label:
        raise IntegrationValidationError(
            "Connection label is required", operation="start_oauth_connect"
        )

    connection_id = payload.connection_id or uuid4()
    is_reauthentication = payload.connection_id is not None
    if payload.connection_id is None:
        stub = ExternalCredential(
            id=uuid4(),
            provider_key=manifest.provider_key,
            auth_mode="oauth",
            principal_fingerprint=f"pending:{connection_id}",
        )
        db.add(stub)
        connection = IntegrationConnection(
            id=connection_id,
            provider_key=manifest.provider_key,
            label=label,
            owner_user_id=actor.id if manifest.owner_scope == "user" else None,
            owner_workspace_id=workspace.id if manifest.owner_scope == "workspace" else None,
            credential_id=stub.id,
            connected_by_user_id=actor.id,
            status=CONNECTION_STATUS_AUTH_PENDING,
        )
        db.add(connection)
    else:
        connection = await get_visible_connection(
            db,
            connection_id=connection_id,
            actor=actor,
            workspace=workspace,
        )
        require_connection_mutation_allowed(connection, actor=actor, membership=membership)
        if (
            connection.provider_key != manifest.provider_key
            or connection.status != CONNECTION_STATUS_NEEDS_REAUTH
        ):
            raise IntegrationConnectionError(
                "Only a matching connection that needs reauthentication can be restarted",
                provider_key=manifest.provider_key,
                connection_id=str(connection.id),
                operation="start_oauth_connect",
            )
        connection.label = label
        await transition_connection_status(
            db,
            connection,
            CONNECTION_STATUS_AUTH_PENDING,
            reason="reauth_started",
            audit_action=AuditAction.CREATE,
            audit_details={
                "provider_key": manifest.provider_key,
                "owner_scope": manifest.owner_scope,
            },
            audit_workspace_id=workspace.id,
        )

    await db.flush()
    await db.execute(
        delete(IntegrationOAuthState).where(IntegrationOAuthState.connection_id == connection.id)
    )
    verifier = generate_code_verifier()
    state, claims = create_integration_oauth_state(
        connection_id=connection.id,
        provider_key=manifest.provider_key,
        owner_scope=manifest.owner_scope,
        workspace_id=workspace.id,
        user_id=actor.id,
        next_path=payload.next_path,
    )
    db.add(
        IntegrationOAuthState(
            jti=claims["jti"],
            connection_id=connection.id,
            code_verifier_encrypted=await encrypt_code_verifier(db, verifier),
            expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
        )
    )
    await db.flush()
    if not is_reauthentication:
        await record_integration_audit(
            db,
            workspace_id=workspace.id,
            action=AuditAction.CREATE,
            resource_type=AuditResourceType.INTEGRATION_CONNECTION,
            resource_id=connection.id,
            details={"provider_key": manifest.provider_key, "owner_scope": manifest.owner_scope},
        )
    return OAuthConnectResponse(
        authorization_url=build_authorization_url(manifest, state=state, code_verifier=verifier),
        state=state,
        connection_id=connection.id,
    )
