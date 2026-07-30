"""Connection transition guard tests."""

from uuid import uuid4

import pytest
from sqlalchemy import delete

from core.exceptions.integration import IntegrationConnectionError
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.user import User
from models.workspace import Workspace
from services.integrations.connections import transition_connection_status
from services.integrations.credentials import revoke_credential
from services.integrations.domain import CONNECTION_STATUS_TRANSITIONS
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
