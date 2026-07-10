"""Credential root-key rotation convergence tests."""

import asyncio
import hashlib
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from core.settings import settings
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential
from models.jobs import Job
from services.integrations.credentials import store_oauth_credential
from services.integrations.utils import (
    _reset_credential_key_cache,
    ensure_credential_keys_loaded,
)
from services.jobs.handlers.rotate_credential_encryption import rotate_credential_encryption

pytestmark = pytest.mark.asyncio


async def test_rotation_reencrypts_under_newest_key_and_old_key_can_be_dropped(
    db_session,
    monkeypatch,
) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIAL_MASTER_KEYS", old_key)
    _reset_credential_key_cache()
    credential = await store_oauth_credential(
        db_session,
        provider_key="test_provider",
        token_payload={"access_token": "access", "refresh_token": "refresh"},
        external_principal_id="rotation-principal",
        external_principal_label=None,
        granted_scopes=[],
    )
    old_key_id = credential.encryption_key_id

    monkeypatch.setattr(settings, "CREDENTIAL_MASTER_KEYS", f"{new_key},{old_key}")
    _reset_credential_key_cache()
    await rotate_credential_encryption(db_session, Job(id=uuid4(), kind="rotation"))
    assert credential.encryption_key_id != old_key_id
    assert credential.access_token == "access"

    monkeypatch.setattr(settings, "CREDENTIAL_MASTER_KEYS", new_key)
    _reset_credential_key_cache()
    await ensure_credential_keys_loaded(db_session)
    assert credential.access_token == "access"
    assert credential.refresh_token == "refresh"
    _reset_credential_key_cache()


async def test_rotation_does_not_restamp_credential_revoked_while_waiting_for_lock(
    committed_db_session_factory,
    monkeypatch,
) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "CREDENTIAL_MASTER_KEYS", old_key)
    _reset_credential_key_cache()
    async with committed_db_session_factory() as setup:
        credential = await store_oauth_credential(
            setup,
            provider_key="test_provider",
            token_payload={"access_token": "access", "refresh_token": "refresh"},
            external_principal_id="concurrent-revocation",
            external_principal_label=None,
            granted_scopes=[],
        )
        await setup.commit()
        credential_id = credential.id

    monkeypatch.setattr(settings, "CREDENTIAL_MASTER_KEYS", f"{new_key},{old_key}")
    _reset_credential_key_cache()
    new_key_id = hashlib.sha256(new_key.encode("ascii")).hexdigest()[:16]

    async def rotate() -> None:
        async with committed_db_session_factory() as rotation_db:
            await rotate_credential_encryption(
                rotation_db,
                Job(id=uuid4(), kind="rotation"),
            )
            await rotation_db.commit()

    try:
        async with committed_db_session_factory() as revoke_db:
            locked = await revoke_db.scalar(
                select(ExternalCredential)
                .where(ExternalCredential.id == credential_id)
                .with_for_update()
            )
            assert locked is not None
            locked.crypto_shred()
            await revoke_db.flush()

            rotation_task = asyncio.create_task(rotate())
            await asyncio.sleep(0.05)
            assert not rotation_task.done()
            await revoke_db.commit()
            await rotation_task

        async with committed_db_session_factory() as verify:
            revoked = await verify.get(ExternalCredential, credential_id)
            assert revoked is not None
            assert revoked.revoked_at is not None
            assert revoked.access_token_encrypted is None
            assert revoked.refresh_token_encrypted is None
            assert revoked.encryption_key_id is None
    finally:
        async with committed_db_session_factory() as cleanup:
            await cleanup.execute(
                delete(AuditEvent).where(
                    (AuditEvent.resource_id == str(credential_id))
                    | (AuditEvent.details["encryption_key_id"].astext == new_key_id)
                )
            )
            await cleanup.execute(
                delete(ExternalCredential).where(ExternalCredential.id == credential_id)
            )
            await cleanup.commit()
        _reset_credential_key_cache()
