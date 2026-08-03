"""Connection transition guard tests."""

import asyncio
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from core.database import (
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
)
from core.exceptions.integration import IntegrationConnectionError
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.integrations.connections import (
    complete_oauth_callback,
    revoke_connection,
    transition_connection_status,
)
from services.integrations.credentials import revoke_credential, store_oauth_credential
from services.integrations.domain import CONNECTION_STATUS_TRANSITIONS
from services.integrations.oauth.fetch_external_principal import ExternalPrincipal
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_user,
    build_workspace,
)

pytestmark = pytest.mark.asyncio


async def _connection(
    db_session,
    *,
    status="auth_pending",
    auth_mode="oauth",
) -> IntegrationConnection:
    user = build_user(email=f"status-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"status-{uuid4()}")
    credential = ExternalCredential(
        provider_key="test_provider",
        auth_mode=auth_mode,
        principal_fingerprint="f" * 64,
        access_token_encrypted="ciphertext" if auth_mode == "oauth" else None,
        secret_provider="local" if auth_mode != "oauth" else None,
        secret_name="reference" if auth_mode != "oauth" else None,
        secret_version="1" if auth_mode != "oauth" else None,
    )
    db_session.add_all([user, workspace, credential])
    await db_session.flush()
    connection = IntegrationConnection(
        provider_key="test_provider",
        label="Status test",
        owner_workspace_id=workspace.id,
        credential_id=credential.id,
        connected_by_user_id=user.id,
        status=status,
    )
    db_session.add(connection)
    await db_session.flush()
    return connection


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in CONNECTION_STATUS_TRANSITIONS.items()
        for target in targets
    ],
)
async def test_every_declared_transition_is_allowed(db_session, source, target) -> None:
    auth_mode = "api_key" if "needs_credential" in {source, target} else "oauth"
    connection = await _connection(db_session, status=source, auth_mode=auth_mode)
    assert await transition_connection_status(db_session, connection, target) is connection
    assert connection.status == target


async def test_illegal_and_terminal_transitions_are_rejected(db_session) -> None:
    connection = await _connection(db_session, status="revoked")
    with pytest.raises(IntegrationConnectionError):
        await transition_connection_status(db_session, connection, "active")


async def test_stale_transition_cannot_resurrect_concurrently_revoked_connection(
    committed_db_session_factory,
) -> None:
    unique_id = uuid4().hex
    user = build_user(email=f"status-race-{unique_id}@example.com")
    workspace = build_workspace(slug=f"status-race-{unique_id}")
    credential = build_external_credential(
        auth_mode="api_key",
        access_token_encrypted=None,
        secret_provider="local_env",  # noqa: S106 - inert test reference metadata
        secret_name="test-secret",  # noqa: S106 - inert test reference metadata
        secret_version="latest",  # noqa: S106 - inert test reference metadata
    )
    async with committed_db_session_factory() as setup:
        setup.add_all([user, workspace, credential])
        await setup.flush()
        connection = build_integration_connection(
            credential=credential,
            user=user,
            workspace=workspace,
            status="discovery_pending",
        )
        setup.add(connection)
        await setup.commit()
        connection_id = connection.id
        credential_id = credential.id
        workspace_id = workspace.id
        user_id = user.id

    try:
        async with committed_db_session_factory() as discovery_db:
            stale_connection = await discovery_db.get(IntegrationConnection, connection_id)
            assert stale_connection is not None

            async with committed_db_session_factory() as revoke_db:
                await revoke_credential(revoke_db, credential_id=credential_id)
                await revoke_db.commit()

            result = await transition_connection_status(
                discovery_db,
                stale_connection,
                "active",
            )
            await discovery_db.commit()

        assert result.status == "revoked"
        async with committed_db_session_factory() as verify:
            persisted = await verify.get(IntegrationConnection, connection_id)
            assert persisted is not None
            assert persisted.status == "revoked"
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(
                delete(AuditEvent).where(
                    AuditEvent.resource_id.in_([str(connection_id), str(credential_id)])
                )
            )
            await cleanup.execute(
                delete(IntegrationConnection).where(IntegrationConnection.id == connection_id)
            )
            await cleanup.execute(
                delete(ExternalCredential).where(ExternalCredential.id == credential_id)
            )
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_callback_cannot_replace_credential_during_connection_revocation(
    committed_db_session_factory,
    monkeypatch,
) -> None:
    from integrations.gmail import PROVIDER as GMAIL_PROVIDER

    unique_id = uuid4().hex
    user = build_user(email=f"revoke-callback-race-{unique_id}@example.com")
    workspace = build_workspace(slug=f"revoke-callback-race-{unique_id}")
    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.ADMIN.value,
    )
    async with committed_db_session_factory() as setup:
        setup.add_all([user, workspace, membership])
        await setup.flush()
        await set_session_tenant_context(
            setup,
            workspace_id=workspace.id,
            user_id=user.id,
        )
        credential = await store_oauth_credential(
            setup,
            provider_key="gmail",
            token_payload={
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "expires_in": 3600,
            },
            external_principal_id="old-principal",
            external_principal_label="old@example.com",
            granted_scopes=[],
            owner_workspace_id=workspace.id,
        )
        connection = build_integration_connection(
            credential=credential,
            user=user,
            workspace=workspace,
            status="auth_pending",
        )
        setup.add(connection)
        await setup.commit()
        connection_id = connection.id
        old_credential_id = credential.id
        workspace_id = workspace.id
        user_id = user.id
        membership_id = membership.id

    revoke_module = import_module("services.integrations.connections.revoke_connection")
    callback_module = import_module("services.integrations.connections.complete_oauth_callback")
    monkeypatch.setitem(
        callback_module.PROVIDER_MANIFESTS,
        "gmail",
        GMAIL_PROVIDER.manifest,
    )
    remote_revocation_started = asyncio.Event()
    finish_remote_revocation = asyncio.Event()
    callback_reached_swap = asyncio.Event()

    async def paused_remote_revocation(**_kwargs) -> None:
        remote_revocation_started.set()
        await finish_remote_revocation.wait()

    async def consume_state(_db, _jti: str) -> str:
        return "encrypted-verifier"

    async def decrypt_verifier(_db, _encrypted_verifier: str) -> str:
        return "verifier"

    async def exchange(**_kwargs) -> dict[str, object]:
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    async def principal(**_kwargs) -> ExternalPrincipal:
        callback_reached_swap.set()
        return ExternalPrincipal(
            f"new-principal-{unique_id}",
            f"new-{unique_id}@example.com",
        )

    monkeypatch.setattr(revoke_module, "revoke_authorization_token", paused_remote_revocation)
    monkeypatch.setattr(
        callback_module,
        "verify_integration_oauth_state",
        lambda _state: {
            "jti": "test-jti",
            "connection_id": str(connection_id),
            "provider_key": "gmail",
            "owner_scope": "workspace",
            "user_id": str(user_id),
            "workspace_id": str(workspace_id),
        },
    )
    monkeypatch.setattr(callback_module, "_consume_pending_state", consume_state)
    monkeypatch.setattr(callback_module, "decrypt_code_verifier", decrypt_verifier)
    monkeypatch.setattr(callback_module, "exchange_authorization_code", exchange)
    monkeypatch.setattr(callback_module, "fetch_external_principal", principal)

    async def revoke() -> None:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            await revoke_connection(
                db,
                connection_id=connection_id,
                actor=user,
                workspace=workspace,
                membership=membership,
            )
            await db.commit()

    async def callback() -> None:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            try:
                await complete_oauth_callback(
                    db,
                    actor=user,
                    workspace=workspace,
                    code="authorization-code",
                    state="signed-state",
                    provider_error=None,
                    ip_address="127.0.0.1",
                    endpoint="/api/v1/integrations/oauth/callback",
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    revoke_task = asyncio.create_task(revoke())
    callback_task = None
    try:
        await asyncio.wait_for(remote_revocation_started.wait(), timeout=5)
        callback_task = asyncio.create_task(callback())
        await asyncio.wait_for(callback_reached_swap.wait(), timeout=5)
        await asyncio.sleep(0.05)
        assert not callback_task.done()

        finish_remote_revocation.set()
        await asyncio.wait_for(revoke_task, timeout=5)
        with pytest.raises(
            IntegrationConnectionError,
            match="changed while authorization was completing",
        ):
            await asyncio.wait_for(callback_task, timeout=5)

        async with committed_db_session_factory() as verify:
            await set_session_tenant_context(
                verify,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            persisted = await verify.get(IntegrationConnection, connection_id)
            assert persisted is not None
            assert persisted.status == "revoked"
            assert persisted.credential_id == old_credential_id
            old_credential = await verify.get(ExternalCredential, old_credential_id)
            assert old_credential is not None
            assert old_credential.revoked_at is not None
            replacement_id = await verify.scalar(
                select(ExternalCredential.id).where(
                    ExternalCredential.external_principal_label == f"new-{unique_id}@example.com"
                )
            )
            assert replacement_id is None
    finally:
        finish_remote_revocation.set()
        if not revoke_task.done():
            revoke_task.cancel()
        if callback_task is not None and not callback_task.done():
            callback_task.cancel()
        tasks = [revoke_task]
        if callback_task is not None:
            tasks.append(callback_task)
        await asyncio.gather(*tasks, return_exceptions=True)
        async with get_maintenance_async_db_session_factory()() as cleanup:
            await cleanup.execute(
                delete(AuditEvent).where(
                    AuditEvent.resource_id.in_([str(connection_id), str(old_credential_id)])
                )
            )
            await cleanup.execute(
                delete(IntegrationConnection).where(IntegrationConnection.id == connection_id)
            )
            await cleanup.execute(
                delete(ExternalCredential).where(ExternalCredential.id == old_credential_id)
            )
            await cleanup.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.id == membership_id)
            )
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()


async def test_same_status_is_noop(db_session) -> None:
    connection = await _connection(db_session, status="active")
    changed_at = connection.status_changed_at
    await transition_connection_status(db_session, connection, "active", reason="ignored")
    assert connection.status_changed_at == changed_at


async def test_recovery_status_must_match_auth_mode(db_session) -> None:
    reference_connection = await _connection(
        db_session,
        status="active",
        auth_mode="service_account",
    )
    with pytest.raises(IntegrationConnectionError):
        await transition_connection_status(db_session, reference_connection, "needs_reauth")

    oauth_connection = await _connection(db_session, status="active", auth_mode="oauth")
    with pytest.raises(IntegrationConnectionError):
        await transition_connection_status(db_session, oauth_connection, "needs_credential")
