# apps/api/services/integrations/connections/connect_api_key.py

"""Connect an API-key provider while retaining only a secret reference."""

import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integrations import IntegrationConnection
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.schemas import ApiKeyConnectRequest, ConnectionRead
from services.integrations.connections.utils import connection_to_read
from services.integrations.credentials import store_secret_reference_credential
from services.integrations.domain import (
    CONNECTION_STATUS_ACTIVE,
    CONNECTION_STATUS_DISCOVERY_PENDING,
)
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.utils import record_integration_audit
from services.secrets import delete_secret, resolve_secret, write_secret
from services.secrets.domain import SecretReference

logger = logging.getLogger(__name__)


async def connect_api_key(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    payload: ApiKeyConnectRequest,
) -> ConnectionRead:
    manifest = PROVIDER_MANIFESTS.get(payload.provider_key)
    if manifest is None or "api_key" not in manifest.auth_modes:
        raise IntegrationValidationError(
            "API-key provider is not enabled",
            provider_key=payload.provider_key,
            operation="connect_api_key",
        )
    label = payload.label.strip()
    if not label:
        raise IntegrationValidationError(
            "Connection label is required", operation="connect_api_key"
        )

    if payload.api_key is not None:
        reference = await write_secret(
            db,
            name=f"integrations-{payload.provider_key}-{uuid4().hex}",
            value=payload.api_key.get_secret_value(),
            workspace_id=workspace.id,
            actor_id=actor.id,
        )
    else:
        if payload.secret_reference is None:  # guarded by request validation
            raise IntegrationValidationError(
                "Secret reference is required", operation="connect_api_key"
            )
        reference = SecretReference(
            provider=payload.secret_reference.provider,
            name=payload.secret_reference.name,
            version=payload.secret_reference.version,
        )
        await resolve_secret(db, reference, workspace_id=workspace.id, actor_id=actor.id)

    try:
        credential = await store_secret_reference_credential(
            db,
            provider_key=manifest.provider_key,
            auth_mode="api_key",
            secret_reference=reference,
            external_principal_id=reference.name,
        )
        connection = IntegrationConnection(
            provider_key=manifest.provider_key,
            label=label,
            owner_workspace_id=workspace.id,
            credential_id=credential.id,
            connected_by_user_id=actor.id,
            status=(
                CONNECTION_STATUS_DISCOVERY_PENDING
                if manifest.requires_discovery
                else CONNECTION_STATUS_ACTIVE
            ),
        )
        db.add(connection)
        await db.flush()
        # Resource discovery will enqueue here once its worker is available.
        await record_integration_audit(
            db,
            workspace_id=workspace.id,
            action=AuditAction.CREATE,
            resource_type=AuditResourceType.INTEGRATION_CONNECTION,
            resource_id=connection.id,
            details={"provider_key": manifest.provider_key, "reference": reference.render()},
        )
        return await connection_to_read(db, connection, include_credential=True)
    except Exception:
        if payload.api_key is not None:
            try:
                await delete_secret(
                    db,
                    reference,
                    workspace_id=workspace.id,
                    actor_id=actor.id,
                )
            except Exception:
                logger.warning(
                    "Failed to clean up an unreferenced integration secret",
                    exc_info=True,
                )
        raise
