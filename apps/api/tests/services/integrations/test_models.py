"""Database-enforced integration model invariants."""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, ProgrammingError

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
            # A missing owner can be rejected by the fail-closed RLS policy
            # before PostgreSQL evaluates the owner XOR constraint.
            with pytest.raises((IntegrityError, ProgrammingError)):
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
