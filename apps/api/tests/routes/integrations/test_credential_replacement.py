"""Credential replacement lifecycle, authorization, and redaction tests."""

import json
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import set_session_tenant_context
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.jobs import Job
from models.workspace import WorkspaceRole
from services.integrations.connections.schemas import CredentialReplacementRequest
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference
from tests.routes.integrations.conftest import create_identity

pytestmark = pytest.mark.asyncio


async def test_api_key_replacement_reuses_connection_and_retains_prior_version(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    initial_value = "initial-api-key-value"
    replacement_value = "replacement-api-key-value"
    connected = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={"provider_key": "airtable", "label": "Operations", "api_key": initial_value},
    )
    assert connected.status_code == 200, connected.text
    connection_id = connected.json()["id"]
    connection = await db_session.get(IntegrationConnection, connection_id)
    assert connection is not None
    credential = await db_session.get(ExternalCredential, connection.credential_id)
    assert credential is not None
    old_reference = SecretReference(
        provider=credential.secret_provider,
        name=credential.secret_name,
        version=credential.secret_version,
    )

    replaced = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection_id}/credential",
        headers=integration_identity["headers"],
        json={"api_key": replacement_value},
    )

    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == connection_id
    assert initial_value not in replaced.text
    assert replacement_value not in replaced.text
    db_session.expire_all()
    persisted = await db_session.get(IntegrationConnection, connection_id)
    updated = await db_session.get(ExternalCredential, persisted.credential_id)
    assert persisted.status == "discovery_pending"
    assert updated.id == credential.id
    assert updated.secret_name == old_reference.name
    assert updated.secret_version != old_reference.version
    assert await resolve_secret(db_session, old_reference) == initial_value
    updated_reference = SecretReference(
        provider=updated.secret_provider,
        name=updated.secret_name,
        version=updated.secret_version,
    )
    assert await resolve_secret(db_session, updated_reference) == replacement_value
    job_count = await db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(
            Job.kind == "integrations.discover_resources",
            Job.subject_id == persisted.id,
        )
    )
    assert job_count == 1
    serialized_audits = json.dumps(
        [event.details for event in (await db_session.scalars(select(AuditEvent))).all()]
    )
    assert initial_value not in serialized_audits
    assert replacement_value not in serialized_audits
    assert replacement_value not in caplog.text


async def test_replacement_rejects_another_workspaces_secret_reference(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    foreign = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={"provider_key": "airtable", "label": "Foreign", "api_key": "foreign-key"},
    )
    assert foreign.status_code == 200, foreign.text
    foreign_connection = await db_session.get(IntegrationConnection, foreign.json()["id"])
    foreign_credential = await db_session.get(
        ExternalCredential,
        foreign_connection.credential_id,
    )

    other_user, other_workspace, _membership, other_headers = await create_identity(
        db_session,
        role=WorkspaceRole.ADMIN,
    )
    owned = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=other_headers,
        json={"provider_key": "airtable", "label": "Owned", "api_key": "owned-key"},
    )
    assert owned.status_code == 200, owned.text
    await set_session_tenant_context(
        db_session,
        workspace_id=other_workspace.id,
        user_id=other_user.id,
    )
    owned_connection = await db_session.get(IntegrationConnection, owned.json()["id"])
    owned_credential = await db_session.get(
        ExternalCredential,
        owned_connection.credential_id,
    )
    original_reference = (
        owned_credential.secret_provider,
        owned_credential.secret_name,
        owned_credential.secret_version,
    )
    owned_credential_id = owned_credential.id

    response = await db_async_client.put(
        f"/api/v1/integrations/connections/{owned_connection.id}/credential",
        headers=other_headers,
        json={
            "secret_reference": {
                "provider": foreign_credential.secret_provider,
                "name": foreign_credential.secret_name,
                "version": foreign_credential.secret_version,
            }
        },
    )

    assert response.status_code == 400
    assert "not authorized for this workspace" in response.text
    assert "foreign-key" not in response.text
    db_session.expire_all()
    persisted = await db_session.get(ExternalCredential, owned_credential_id)
    assert (
        persisted.secret_provider,
        persisted.secret_name,
        persisted.secret_version,
    ) == original_reference


async def test_replacement_rejects_member_and_revoked_connection(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    api_key = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={"provider_key": "airtable", "label": "Key", "api_key": "initial-key"},
    )
    assert api_key.status_code == 200, api_key.text
    connection_id = api_key.json()["id"]
    _user, _workspace, _membership, member_headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=integration_identity["workspace"],
    )
    denied = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection_id}/credential",
        headers=member_headers,
        json={"api_key": "replacement"},
    )
    assert denied.status_code == 403

    connection = await db_session.get(IntegrationConnection, connection_id)
    connection.status = "revoked"
    await db_session.commit()
    revoked = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection_id}/credential",
        headers=integration_identity["headers"],
        json={"api_key": "replacement"},
    )
    assert revoked.status_code == 400


async def test_new_local_version_is_cleaned_up_when_locked_rows_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.connections.replace_credential")
    connection_id = uuid4()
    credential_id = uuid4()
    visible = SimpleNamespace(
        id=connection_id,
        credential_id=credential_id,
        provider_key="airtable",
        status="active",
        owner_workspace_id=uuid4(),
        owner_user_id=None,
    )
    credential = SimpleNamespace(
        id=credential_id,
        auth_mode="api_key",
        deleted=False,
        revoked_at=None,
        secret_name="integrations-airtable-managed",  # noqa: S106 - inert reference name
    )
    reference = SecretReference(
        provider="local",
        name="integrations-airtable-managed",
        version="00000002",
    )
    deleted: list[SecretReference] = []

    async def get_visible(*args, **kwargs):
        return visible

    async def write(*args, **kwargs):
        return reference

    async def changed(*args, **kwargs):
        raise RuntimeError("connection changed")

    class Provider:
        async def delete_secret(self, target):
            deleted.append(target)
            return True

    monkeypatch.setattr(module, "get_visible_connection", get_visible)
    monkeypatch.setattr(module, "require_connection_mutation_allowed", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "write_secret", write)
    monkeypatch.setattr(module, "_lock_current_rows", changed)
    monkeypatch.setattr(module, "get_secrets_provider", Provider)

    class Db:
        async def get(self, model, target_id):
            return credential

    with pytest.raises(RuntimeError, match="connection changed"):
        await module.replace_credential(
            Db(),
            connection_id=connection_id,
            actor=SimpleNamespace(id=uuid4()),
            workspace=SimpleNamespace(id=visible.owner_workspace_id),
            membership=SimpleNamespace(role="owner"),
            payload=CredentialReplacementRequest(api_key="replacement"),
        )

    assert deleted == [reference]
