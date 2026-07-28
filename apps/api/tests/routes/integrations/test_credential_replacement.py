"""Credential replacement lifecycle, authorization, and redaction tests."""

import json
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.jobs import Job
from models.workspace import WorkspaceRole
from services.integrations.connections.schemas import CredentialReplacementRequest
from services.integrations.utils import _reset_credential_key_cache
from services.secrets import resolve_secret, write_secret
from services.secrets.domain import SecretReference
from tests.routes.integrations.conftest import create_identity

pytestmark = pytest.mark.asyncio


def _service_account_json(email: str, private_key: str) -> str:
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "praxis-analytics",
            "client_email": email,
            "private_key": private_key,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


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


async def test_service_account_and_reference_replacements_update_metadata(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connected = await db_async_client.post(
        "/api/v1/integrations/connections/service-account",
        headers=integration_identity["headers"],
        json={
            "provider_key": "google_ads",
            "label": "Agency",
            "service_account_json": _service_account_json(
                "first@example.iam.gserviceaccount.com",
                "first-private-key",
            ),
        },
    )
    assert connected.status_code == 200, connected.text
    connection_id = connected.json()["id"]
    replacement_value = _service_account_json(
        "second@example.iam.gserviceaccount.com",
        "second-private-key",
    )
    reference = await write_secret(
        db_session,
        name=f"integration-test-reference-{uuid4().hex}",
        value=replacement_value,
        workspace_id=integration_identity["workspace"].id,
        actor_id=integration_identity["user"].id,
    )
    # A long-lived connection can be replaced immediately after an API process
    # restart, before another credential flow has initialized process-local keys.
    _reset_credential_key_cache()

    replaced = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection_id}/credential",
        headers=integration_identity["headers"],
        json={
            "secret_reference": {
                "provider": reference.provider,
                "name": reference.name,
                "version": reference.version,
            }
        },
    )

    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] == connection_id
    assert "second-private-key" not in replaced.text
    db_session.expire_all()
    connection = await db_session.get(IntegrationConnection, connection_id)
    credential = await db_session.get(ExternalCredential, connection.credential_id)
    assert connection.provider_metadata["service_account_email"] == (
        "second@example.iam.gserviceaccount.com"
    )
    assert credential.external_principal_label == "second@example.iam.gserviceaccount.com"
    assert (
        credential.secret_provider,
        credential.secret_name,
        credential.secret_version,
    ) == (reference.provider, reference.name, reference.version)


async def test_replacement_rejects_wrong_mode_oauth_revoked_and_member(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    api_key = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={"provider_key": "airtable", "label": "Key", "api_key": "initial-key"},
    )
    connection_id = api_key.json()["id"]
    wrong_mode = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection_id}/credential",
        headers=integration_identity["headers"],
        json={
            "service_account_json": _service_account_json(
                "wrong@example.iam.gserviceaccount.com",
                "private-key",
            )
        },
    )
    assert wrong_mode.status_code == 400

    oauth = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=integration_identity["headers"],
        json={
            "provider_key": "gmail",
            "owner_scope": "user",
            "label": "Inbox",
        },
    )
    oauth_replacement = await db_async_client.put(
        f"/api/v1/integrations/connections/{oauth.json()['connection_id']}/credential",
        headers=integration_identity["headers"],
        json={"api_key": "not-oauth"},
    )
    assert oauth_replacement.status_code == 400
    assert "sign-in flow" in oauth_replacement.text

    connection = await db_session.get(IntegrationConnection, connection_id)
    connection.status = "revoked"
    await db_session.commit()
    revoked = await db_async_client.put(
        f"/api/v1/integrations/connections/{connection_id}/credential",
        headers=integration_identity["headers"],
        json={"api_key": "replacement"},
    )
    assert revoked.status_code == 400

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


async def test_non_oauth_refresh_is_rejected_without_mutation(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connected = await db_async_client.post(
        "/api/v1/integrations/connections/api-key",
        headers=integration_identity["headers"],
        json={"provider_key": "airtable", "label": "Key", "api_key": "initial-key"},
    )
    connection_id = connected.json()["id"]
    connection = await db_session.get(IntegrationConnection, connection_id)
    credential = await db_session.get(ExternalCredential, connection.credential_id)
    before = (connection.status, credential.refresh_failure_count)

    response = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/refresh",
        headers=integration_identity["headers"],
    )

    assert response.status_code == 400
    db_session.expire_all()
    connection = await db_session.get(IntegrationConnection, connection_id)
    credential = await db_session.get(ExternalCredential, connection.credential_id)
    assert (connection.status, credential.refresh_failure_count) == before


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
