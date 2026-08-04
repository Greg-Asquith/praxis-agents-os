"""Application encryption convergence and removal-proof job tests."""

from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select, update

from core.database import SESSION_MAINTENANCE_KEY
from core.settings import settings
from models.audit_event import AuditEvent
from models.jobs import Job
from models.user import User, UserAuth
from services.audit_events import AuditResourceType
from services.jobs.handlers.converge_application_encryption import (
    APPLICATION_ENCRYPTION_JOB_KIND,
    converge_application_encryption,
)
from services.security.ensure_application_encryption_keys_loaded import (
    _reset_application_encryption_key_cache,
)
from tests.factories.users import build_user
from utils.security import (
    configure_application_encryption_keys,
    decrypt_data,
    encrypt_data,
    is_encrypted_with_primary,
)


async def test_sweep_converges_all_durable_fields_and_is_idempotent(
    db_session,
    monkeypatch,
) -> None:
    async def flush_without_ending_test_transaction() -> None:
        await db_session.flush()

    db_session.info[SESSION_MAINTENANCE_KEY] = True
    monkeypatch.setattr(db_session, "commit", flush_without_ending_test_transaction)
    await db_session.execute(
        update(User).values(totp_secret_encrypted=None, backup_codes_encrypted=None)
    )
    await db_session.execute(
        update(UserAuth).values(access_token_encrypted=None, refresh_token_encrypted=None)
    )
    original_keys = settings.application_encryption_keys
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    configure_application_encryption_keys((old_key,))

    user = build_user(email=f"encryption-rotation-{uuid4().hex}@example.com")
    user.totp_secret_encrypted = encrypt_data("totp-secret")
    user.backup_codes_encrypted = encrypt_data('["backup-hash"]')
    auth = UserAuth(
        user=user,
        provider="test",
        provider_user_id=f"rotation-{uuid4().hex}",
        email=user.email,
        access_token_encrypted=encrypt_data("access-token"),
        refresh_token_encrypted=encrypt_data("refresh-token"),
    )
    db_session.add_all([user, auth])
    await db_session.flush()

    monkeypatch.setattr(
        settings,
        "ENCRYPTION_KEYS",
        [SecretStr(new_key), SecretStr(old_key)],
    )
    _reset_application_encryption_key_cache()

    try:
        check_job = Job(
            id=uuid4(),
            kind=APPLICATION_ENCRYPTION_JOB_KIND,
            payload={"mode": "check"},
        )
        await converge_application_encryption(db_session, check_job)
        assert check_job.payload["result"] == {
            "total": 4,
            "primary": 0,
            "stale": 4,
            "undecryptable": 0,
            "rotated": 0,
        }

        converge_job = Job(
            id=uuid4(),
            kind=APPLICATION_ENCRYPTION_JOB_KIND,
            payload={"mode": "converge"},
        )
        await converge_application_encryption(db_session, converge_job)
        assert converge_job.payload["result"]["rotated"] == 4
        assert all(
            is_encrypted_with_primary(value)
            for value in (
                user.totp_secret_encrypted,
                user.backup_codes_encrypted,
                auth.access_token_encrypted,
                auth.refresh_token_encrypted,
            )
        )

        repeat_job = Job(
            id=uuid4(),
            kind=APPLICATION_ENCRYPTION_JOB_KIND,
            payload={"mode": "converge"},
        )
        await converge_application_encryption(db_session, repeat_job)
        assert repeat_job.payload["result"] == {
            "total": 4,
            "primary": 4,
            "stale": 0,
            "undecryptable": 0,
            "rotated": 0,
        }
        audit_events = list(
            (
                await db_session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_type == AuditResourceType.APPLICATION_ENCRYPTION.value,
                        AuditEvent.resource_id.in_(
                            (str(check_job.id), str(converge_job.id), str(repeat_job.id))
                        ),
                    )
                )
            ).all()
        )
        assert {event.resource_id for event in audit_events} == {
            str(check_job.id),
            str(converge_job.id),
            str(repeat_job.id),
        }
        assert {event.details["mode"] for event in audit_events} == {"check", "converge"}
        assert all(
            event.details["job_kind"] == APPLICATION_ENCRYPTION_JOB_KIND for event in audit_events
        )

        configure_application_encryption_keys((new_key,))
        assert decrypt_data(user.totp_secret_encrypted) == "totp-secret"
        assert decrypt_data(user.backup_codes_encrypted) == '["backup-hash"]'
        assert decrypt_data(auth.access_token_encrypted) == "access-token"
        assert decrypt_data(auth.refresh_token_encrypted) == "refresh-token"
    finally:
        configure_application_encryption_keys(original_keys)
        _reset_application_encryption_key_cache()


async def test_check_counts_undecryptable_values_without_failing(
    db_session,
    monkeypatch,
) -> None:
    async def flush_without_ending_test_transaction() -> None:
        await db_session.flush()

    db_session.info[SESSION_MAINTENANCE_KEY] = True
    monkeypatch.setattr(db_session, "commit", flush_without_ending_test_transaction)
    await db_session.execute(
        update(User).values(totp_secret_encrypted=None, backup_codes_encrypted=None)
    )
    await db_session.execute(
        update(UserAuth).values(access_token_encrypted=None, refresh_token_encrypted=None)
    )
    original_keys = settings.application_encryption_keys
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "ENCRYPTION_KEYS", [SecretStr(key)])
    _reset_application_encryption_key_cache()

    user = build_user(email=f"encryption-corrupt-{uuid4().hex}@example.com")
    user.totp_secret_encrypted = "corrupt-token"
    db_session.add(user)
    await db_session.flush()

    try:
        job = Job(
            id=uuid4(),
            kind=APPLICATION_ENCRYPTION_JOB_KIND,
            payload={"mode": "check"},
        )
        await converge_application_encryption(db_session, job)
        assert job.payload["result"] == {
            "total": 1,
            "primary": 0,
            "stale": 0,
            "undecryptable": 1,
            "rotated": 0,
        }
        audit_event = await db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_type == AuditResourceType.APPLICATION_ENCRYPTION.value,
                AuditEvent.resource_id == str(job.id),
            )
        )
        assert audit_event is not None
        assert audit_event.details["mode"] == "check"
        assert audit_event.details["undecryptable"] == 1
    finally:
        configure_application_encryption_keys(original_keys)
        _reset_application_encryption_key_cache()
