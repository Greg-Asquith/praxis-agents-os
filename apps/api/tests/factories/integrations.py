# apps/api/tests/factories/integrations.py

"""Integration model factories for service tests."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from models.conversation import Conversation
from models.integration_context import (
    ActiveContextSelection,
    IntegrationContextGroup,
    IntegrationContextGroupMember,
)
from models.integration_table_schema import IntegrationTableSchema
from models.integrations import (
    ExternalCredential,
    IntegrationConnection,
    IntegrationDiscoveryRun,
    IntegrationEvent,
    IntegrationResource,
    IntegrationWebhook,
)
from models.user import User
from models.workspace import Workspace


def build_external_credential(**overrides) -> ExternalCredential:
    defaults = {
        "id": uuid4(),
        "provider_key": "test_provider",
        "auth_mode": "oauth",
        "principal_fingerprint": "f" * 64,
        "access_token_encrypted": "ciphertext",
    }
    defaults.update(overrides)
    return ExternalCredential(**defaults)


def build_integration_connection(
    *,
    credential: ExternalCredential,
    user: User,
    workspace: Workspace | None = None,
    owner_user_id: UUID | None = None,
    **overrides,
) -> IntegrationConnection:
    credential.owner_workspace_id = workspace.id if workspace is not None else None
    credential.owner_user_id = owner_user_id
    defaults = {
        "id": uuid4(),
        "provider_key": credential.provider_key,
        "label": "Test connection",
        "owner_workspace_id": workspace.id if workspace is not None else None,
        "owner_user_id": owner_user_id,
        "credential_id": credential.id,
        "connected_by_user_id": user.id,
    }
    defaults.update(overrides)
    return IntegrationConnection(**defaults)


def build_integration_resource(
    *,
    connection: IntegrationConnection,
    **overrides,
) -> IntegrationResource:
    now = datetime.now(UTC)
    defaults = {
        "id": uuid4(),
        "connection_id": connection.id,
        "resource_type": "test_resource",
        "external_id": "resource-1",
        "display_name": "Test resource",
        "first_seen_at": now,
        "last_seen_at": now,
    }
    defaults.update(overrides)
    return IntegrationResource(**defaults)


def build_integration_table_schema(
    *,
    resource: IntegrationResource,
    **overrides,
) -> IntegrationTableSchema:
    now = datetime.now(UTC)
    defaults = {
        "id": uuid4(),
        "resource_id": resource.id,
        "table_external_id": "table_1",
        "table_type": "table",
        "schema_fields": [],
        "partitioning": {},
        "clustering_fields": [],
        "availability": "available",
        "first_synced_at": now,
        "last_synced_at": now,
    }
    defaults.update(overrides)
    return IntegrationTableSchema(**defaults)


def build_integration_discovery_run(
    *,
    connection: IntegrationConnection,
    **overrides,
) -> IntegrationDiscoveryRun:
    defaults = {
        "id": uuid4(),
        "connection_id": connection.id,
        "status": "succeeded",
        "started_at": datetime.now(UTC),
        "finished_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return IntegrationDiscoveryRun(**defaults)


def build_integration_webhook(
    *,
    connection: IntegrationConnection,
    resource: IntegrationResource | None = None,
    **overrides,
) -> IntegrationWebhook:
    defaults = {
        "id": uuid4(),
        "provider_key": connection.provider_key,
        "connection_id": connection.id,
        "resource_id": resource.id if resource is not None else None,
        "external_resource_id": resource.external_id if resource is not None else "resource-1",
        "receipt_id": uuid4().hex,
        "external_webhook_id": f"hook-{uuid4().hex}",
        "secret_provider": "local",
        "secret_name": "test/webhook/secret",
        "secret_version": "00000001",
        "status": "active",
    }
    defaults.update(overrides)
    return IntegrationWebhook(**defaults)


def build_integration_event(
    *,
    connection: IntegrationConnection,
    webhook: IntegrationWebhook,
    **overrides,
) -> IntegrationEvent:
    defaults = {
        "id": uuid4(),
        "provider_key": connection.provider_key,
        "connection_id": connection.id,
        "webhook_id": webhook.id,
        "external_event_id": f"event-{uuid4().hex}",
        "event_type": "test.event",
        "payload_digest": "d" * 64,
        "dedup_key": f"dedup-{uuid4().hex}",
        "status": "received",
    }
    defaults.update(overrides)
    return IntegrationEvent(**defaults)


def build_integration_context_group(
    *,
    workspace: Workspace,
    user: User,
    resources: list[IntegrationResource] | None = None,
    **overrides,
) -> IntegrationContextGroup:
    defaults = {
        "id": uuid4(),
        "workspace_id": workspace.id,
        "name": "Test context",
        "created_by_user_id": user.id,
        "members": [
            IntegrationContextGroupMember(integration_resource_id=resource.id)
            for resource in resources or []
        ],
    }
    defaults.update(overrides)
    return IntegrationContextGroup(**defaults)


def build_active_context_selection(
    *,
    workspace: Workspace,
    conversation: Conversation,
    resource: IntegrationResource | None = None,
    group: IntegrationContextGroup | None = None,
    **overrides,
) -> ActiveContextSelection:
    defaults = {
        "id": uuid4(),
        "workspace_id": workspace.id,
        "conversation_id": conversation.id,
        "integration_resource_id": resource.id if resource is not None else None,
        "context_group_id": group.id if group is not None else None,
    }
    defaults.update(overrides)
    return ActiveContextSelection(**defaults)
