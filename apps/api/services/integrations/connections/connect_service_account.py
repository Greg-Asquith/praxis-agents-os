# apps/api/services/integrations/connections/connect_service_account.py

"""Connect a workspace provider using reference-only service-account credentials."""

import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationValidationError
from models.integrations import IntegrationConnection
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.schemas import ConnectionRead, ServiceAccountConnectRequest
from services.integrations.connections.utils import connection_to_read
from services.integrations.credentials import (
    parse_google_service_account_json,
    store_secret_reference_credential,
)
from services.integrations.discovery import enqueue_discovery
from services.integrations.domain import CONNECTION_STATUS_DISCOVERY_PENDING
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.utils import record_integration_audit
from services.secrets import delete_secret, resolve_secret, write_secret
from services.secrets.domain import SecretReference

logger = logging.getLogger(__name__)


async def connect_service_account(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    payload: ServiceAccountConnectRequest,
) -> ConnectionRead:
    manifest = PROVIDER_MANIFESTS.get(payload.provider_key)
    if manifest is None or "service_account" not in manifest.auth_modes:
        raise IntegrationValidationError(
            "Service-account provider is not enabled",
            provider_key=payload.provider_key,
            operation="connect_service_account",
        )
    label = payload.label.strip()
    if not label:
        raise IntegrationValidationError(
            "Connection label is required", operation="connect_service_account"
        )

    created_secret = payload.service_account_json is not None
    if created_secret:
        raw_value = payload.service_account_json.get_secret_value()
        parsed = parse_google_service_account_json(raw_value)
        reference = await write_secret(
            db,
            name=f"integrations-{payload.provider_key}-{uuid4().hex}",
            value=raw_value,
            workspace_id=workspace.id,
            actor_id=actor.id,
        )
    else:
        if payload.secret_reference is None:
            raise IntegrationValidationError(
                "Secret reference is required", operation="connect_service_account"
            )
        reference = SecretReference(
            provider=payload.secret_reference.provider,
            name=payload.secret_reference.name,
            version=payload.secret_reference.version,
        )
        raw_value = await resolve_secret(
            db, reference, workspace_id=workspace.id, actor_id=actor.id
        )
        parsed = parse_google_service_account_json(raw_value)

    try:
        credential = await store_secret_reference_credential(
            db,
            provider_key=manifest.provider_key,
            auth_mode="service_account",
            secret_reference=reference,
            external_principal_id=parsed.client_email,
            external_principal_label=parsed.client_email,
        )
        connection = IntegrationConnection(
            provider_key=manifest.provider_key,
            label=label,
            owner_workspace_id=workspace.id,
            credential_id=credential.id,
            connected_by_user_id=actor.id,
            status=CONNECTION_STATUS_DISCOVERY_PENDING,
            provider_metadata={"service_account_email": parsed.client_email},
        )
        db.add(connection)
        await db.flush()
        await enqueue_discovery(db, connection=connection)
        await record_integration_audit(
            db,
            workspace_id=workspace.id,
            action=AuditAction.CREATE,
            resource_type=AuditResourceType.INTEGRATION_CONNECTION,
            resource_id=connection.id,
            details={
                "provider_key": manifest.provider_key,
                "auth_mode": "service_account",
                "reference": reference.render(),
                "service_account_email": parsed.client_email,
            },
        )
        return await connection_to_read(db, connection, include_credential=True)
    except Exception:
        if created_secret:
            try:
                await delete_secret(db, reference, workspace_id=workspace.id, actor_id=actor.id)
            except Exception:
                logger.warning(
                    "Failed to clean up an unreferenced integration secret", exc_info=True
                )
        raise
