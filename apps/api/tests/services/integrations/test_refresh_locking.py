"""Real-Postgres serialization test for rotating OAuth refresh tokens."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from core.exceptions.integration import IntegrationAuthError
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.user import User
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.integrations.connections import test_connection as run_connection_test
from services.integrations.credentials import ensure_fresh_credential, store_oauth_credential

pytestmark = pytest.mark.asyncio


async def test_concurrent_refresh_hits_provider_once(committed_db_session_factory) -> None:
    email = f"refresh-lock-{uuid4()}@example.com"
    slug = f"refresh-lock-{uuid4()}"
    async with committed_db_session_factory() as setup:
        user = User(email=email, display_name="Refresh lock", is_active=True)
        workspace = Workspace(slug=slug, name="Refresh lock", is_personal=False)
        setup.add_all([user, workspace])
        await setup.flush()
        credential = await store_oauth_credential(
            setup,
            provider_key="test_provider",
            token_payload={
                "access_token": "old-access",
                "refresh_token": "single-use-refresh",
                "expires_in": 1,
            },
            external_principal_id=str(uuid4()),
            external_principal_label=None,
            granted_scopes=[],
        )
        credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        connection = IntegrationConnection(
            provider_key="test_provider",
            label="Refresh lock",
            owner_workspace_id=workspace.id,
            credential_id=credential.id,
            connected_by_user_id=user.id,
            status="active",
        )
        setup.add(connection)
        await setup.commit()
        credential_id = credential.id
        connection_id = connection.id
        workspace_id = workspace.id
        user_id = user.id

    refresh_calls = 0

    async def refresh(_credential):
        nonlocal refresh_calls
        refresh_calls += 1
        await asyncio.sleep(0.05)
        return {
            "access_token": "rotated-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        }

    async def caller() -> str | None:
        async with committed_db_session_factory() as session:
            result = await ensure_fresh_credential(
                session,
                credential_id=credential_id,
                refresh_token=refresh,
            )
            await session.commit()
            return result.access_token

    try:
        assert await asyncio.gather(caller(), caller()) == [
            "rotated-access",
            "rotated-access",
        ]
        assert refresh_calls == 1
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(
                delete(AuditEvent).where(
                    (AuditEvent.resource_id == str(credential_id))
                    | (AuditEvent.resource_id == str(connection_id))
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

    async with committed_db_session_factory() as verify:
        assert (
            await verify.scalar(
                select(ExternalCredential.id).where(ExternalCredential.id == credential_id)
            )
            is None
        )


async def test_auth_refresh_failure_survives_request_style_rollback(
    committed_db_session_factory,
) -> None:
    email = f"refresh-failure-{uuid4()}@example.com"
    slug = f"refresh-failure-{uuid4()}"
    async with committed_db_session_factory() as setup:
        user = User(email=email, display_name="Refresh failure", is_active=True)
        workspace = Workspace(slug=slug, name="Refresh failure", is_personal=False)
        setup.add_all([user, workspace])
        await setup.flush()
        credential = await store_oauth_credential(
            setup,
            provider_key="test_provider",
            token_payload={
                "access_token": "old-access",
                "refresh_token": "invalid-refresh",
                "expires_in": 1,
            },
            external_principal_id=str(uuid4()),
            external_principal_label=None,
            granted_scopes=[],
        )
        credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        connection = IntegrationConnection(
            provider_key="test_provider",
            label="Refresh failure",
            owner_workspace_id=workspace.id,
            credential_id=credential.id,
            connected_by_user_id=user.id,
            status="active",
        )
        setup.add(connection)
        await setup.commit()
        credential_id = credential.id
        connection_id = connection.id
        workspace_id = workspace.id
        user_id = user.id

    try:
        unrelated_workspace_id = uuid4()
        async with committed_db_session_factory() as request_db:
            request_db.add(
                Workspace(
                    id=unrelated_workspace_id,
                    slug=f"must-rollback-{unrelated_workspace_id}",
                    name="Must roll back",
                    is_personal=False,
                )
            )
            await request_db.flush()
            with pytest.raises(IntegrationAuthError):
                await ensure_fresh_credential(request_db, credential_id=credential_id)
            # Mirrors the request dependency's rollback after an exception escapes.
            await request_db.rollback()

        async with committed_db_session_factory() as verify:
            durable_credential = await verify.get(ExternalCredential, credential_id)
            durable_connection = await verify.get(IntegrationConnection, connection_id)
            assert durable_credential is not None
            assert durable_credential.refresh_failure_count == 1
            assert durable_connection is not None
            assert durable_connection.status == "needs_reauth"
            assert await verify.get(Workspace, unrelated_workspace_id) is None
            assert (
                await verify.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.resource_id == str(credential_id),
                        AuditEvent.status == "failure",
                    )
                )
                is not None
            )
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(
                delete(AuditEvent).where(
                    (AuditEvent.resource_id == str(credential_id))
                    | (AuditEvent.resource_id == str(connection_id))
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


async def test_identity_failure_transition_survives_request_style_rollback(
    committed_db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"identity-failure-{uuid4()}@example.com"
    slug = f"identity-failure-{uuid4()}"
    async with committed_db_session_factory() as setup:
        user = User(email=email, display_name="Identity failure", is_active=True)
        workspace = Workspace(slug=slug, name="Identity failure", is_personal=False)
        setup.add_all([user, workspace])
        await setup.flush()
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER,
        )
        credential = await store_oauth_credential(
            setup,
            provider_key="gmail",
            token_payload={
                "access_token": "rejected-access",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
            },
            external_principal_id=str(uuid4()),
            external_principal_label=None,
            granted_scopes=[],
        )
        connection = IntegrationConnection(
            provider_key="gmail",
            label="Identity failure",
            owner_user_id=user.id,
            credential_id=credential.id,
            connected_by_user_id=user.id,
            status="active",
        )
        setup.add_all([membership, connection])
        await setup.commit()
        credential_id = credential.id
        connection_id = connection.id
        membership_id = membership.id
        workspace_id = workspace.id
        user_id = user.id

    module = __import__(
        "services.integrations.connections.test_connection",
        fromlist=["fetch_external_principal"],
    )

    async def rejected_identity(**kwargs):
        raise IntegrationAuthError(
            "Identity rejected",
            provider_key="gmail",
            operation="oauth_userinfo",
        )

    monkeypatch.setattr(module, "fetch_external_principal", rejected_identity)
    try:
        async with committed_db_session_factory() as request_db:
            request_user = await request_db.get(User, user_id)
            request_workspace = await request_db.get(Workspace, workspace_id)
            request_membership = await request_db.get(WorkspaceMembership, membership_id)
            assert request_user is not None
            assert request_workspace is not None
            assert request_membership is not None
            with pytest.raises(IntegrationAuthError):
                await run_connection_test(
                    request_db,
                    connection_id=connection_id,
                    actor=request_user,
                    workspace=request_workspace,
                    membership=request_membership,
                )
            await request_db.rollback()

        async with committed_db_session_factory() as verify:
            durable_connection = await verify.get(IntegrationConnection, connection_id)
            assert durable_connection is not None
            assert durable_connection.status == "needs_reauth"
            assert (
                await verify.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.resource_id == str(connection_id),
                        AuditEvent.status == "failure",
                    )
                )
                is not None
            )
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(
                delete(AuditEvent).where(
                    (AuditEvent.resource_id == str(credential_id))
                    | (AuditEvent.resource_id == str(connection_id))
                )
            )
            await cleanup.execute(
                delete(IntegrationConnection).where(IntegrationConnection.id == connection_id)
            )
            await cleanup.execute(
                delete(ExternalCredential).where(ExternalCredential.id == credential_id)
            )
            await cleanup.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.id == membership_id)
            )
            await cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()
