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
from models.integrations import (
    ExternalCredential,
    IntegrationConnection,
    IntegrationDiscoveryRun,
    IntegrationResource,
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
