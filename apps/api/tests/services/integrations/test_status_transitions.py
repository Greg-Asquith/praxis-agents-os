"""Connection transition guard tests."""

from uuid import uuid4

import pytest

from core.exceptions.integration import IntegrationConnectionError
from models.integrations import ExternalCredential, IntegrationConnection
from services.integrations.connections import transition_connection_status
from services.integrations.domain import CONNECTION_STATUS_TRANSITIONS
from tests.factories import build_user, build_workspace

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
