"""Database-enforced integration model invariants."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from models.integrations import ExternalCredential, IntegrationConnection
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _owners(db_session):
    user = build_user(email=f"integration-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"integration-{uuid4()}")
    db_session.add_all([user, workspace])
    await db_session.flush()
    return user, workspace


def _credential() -> ExternalCredential:
    return ExternalCredential(
        provider_key="test_provider",
        auth_mode="oauth",
        principal_fingerprint="f" * 64,
        access_token_encrypted="ciphertext",  # noqa: S106 - inert encrypted-column fixture
    )


async def test_connection_owner_xor_and_label_checks(db_session) -> None:
    user, workspace = await _owners(db_session)
    for owners, label in (
        ({}, "Valid"),
        ({"owner_user_id": user.id, "owner_workspace_id": workspace.id}, "Valid"),
        ({"owner_workspace_id": workspace.id}, "   "),
    ):
        credential = _credential()
        db_session.add(credential)
        await db_session.flush()
        async with db_session.begin_nested():
            with pytest.raises(IntegrityError):
                db_session.add(
                    IntegrationConnection(
                        provider_key="test_provider",
                        label=label,
                        credential_id=credential.id,
                        connected_by_user_id=user.id,
                        **owners,
                    )
                )
                await db_session.flush()


async def test_status_and_mode_payload_checks(db_session) -> None:
    user, workspace = await _owners(db_session)
    credential = _credential()
    db_session.add(credential)
    await db_session.flush()
    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            db_session.add(
                IntegrationConnection(
                    provider_key="test_provider",
                    label="Invalid status",
                    owner_workspace_id=workspace.id,
                    credential_id=credential.id,
                    connected_by_user_id=user.id,
                    status="unknown",
                )
            )
            await db_session.flush()

    invalid_credentials = (
        ExternalCredential(
            provider_key="test_provider",
            auth_mode="api_key",
            principal_fingerprint="b" * 64,
            secret_provider="local",  # noqa: S106
            secret_name="secret",  # noqa: S106
        ),
        ExternalCredential(
            provider_key="test_provider",
            auth_mode="oauth",
            principal_fingerprint="c" * 64,
            secret_provider="local",  # noqa: S106
        ),
        ExternalCredential(
            provider_key="test_provider",
            auth_mode="oauth",
            principal_fingerprint="d" * 64,
            secret_version="latest",  # noqa: S106
        ),
    )
    for invalid_credential in invalid_credentials:
        async with db_session.begin_nested():
            with pytest.raises(IntegrityError):
                db_session.add(invalid_credential)
                await db_session.flush()

    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            db_session.add(
                ExternalCredential(
                    provider_key="test_provider",
                    auth_mode="api_key",
                    principal_fingerprint="a" * 64,
                    access_token_encrypted="must-not-exist",  # noqa: S106
                    secret_provider="local",  # noqa: S106
                    secret_name="secret",  # noqa: S106
                )
            )
            await db_session.flush()


async def test_multi_connection_same_owner_and_provider_is_allowed(db_session) -> None:
    user, workspace = await _owners(db_session)
    first = _credential()
    second = _credential()
    db_session.add_all([first, second])
    await db_session.flush()
    # Multi-connection is the contract; adding owner/provider uniqueness is a regression.
    db_session.add_all(
        [
            IntegrationConnection(
                provider_key="test_provider",
                label="First",
                owner_workspace_id=workspace.id,
                credential_id=first.id,
                connected_by_user_id=user.id,
            ),
            IntegrationConnection(
                provider_key="test_provider",
                label="Second",
                owner_workspace_id=workspace.id,
                credential_id=second.id,
                connected_by_user_id=user.id,
            ),
        ]
    )
    await db_session.flush()
