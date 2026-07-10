"""Encrypted local secrets provider behavior."""

import pytest
from sqlalchemy import delete, select

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from models.audit_event import AuditEvent
from services.secrets import delete_secret, factory as secrets_factory, resolve_secret, write_secret
from services.secrets.domain import SecretReference
from services.secrets.providers.local import LocalSecretsProvider
from services.secrets.utils import secret_environment_name

pytestmark = pytest.mark.asyncio


async def test_env_resolution_and_encrypted_file_round_trip(tmp_path, monkeypatch) -> None:
    provider = LocalSecretsProvider(storage_root=tmp_path / "storage")
    env_name = secret_environment_name("integrations/example/token")
    monkeypatch.setenv(env_name, "from-environment")
    assert (
        await provider.resolve_secret(
            SecretReference(provider="local", name="integrations/example/token", version="env")
        )
        == "from-environment"
    )
    monkeypatch.delenv(env_name)

    ref = await provider.write_secret("integrations/example/token", "plain-secret-value")
    assert await provider.resolve_secret(ref) == "plain-secret-value"
    assert "plain-secret-value" not in provider.store_path.read_text(encoding="utf-8")
    assert oct(provider.store_path.stat().st_mode & 0o777) == "0o600"


async def test_missing_local_secret_raises_typed_error(tmp_path) -> None:
    provider = LocalSecretsProvider(storage_root=tmp_path / "storage")
    with pytest.raises(IntegrationAuthError):
        await provider.resolve_secret(
            SecretReference(provider="local", name="missing", version="latest")
        )


async def test_write_versions_and_delete(tmp_path) -> None:
    provider = LocalSecretsProvider(storage_root=tmp_path / "storage")
    first = await provider.write_secret("rotating", "one")
    second = await provider.write_secret("rotating", "two")
    assert first.version == "00000001"
    assert second.version == "00000002"
    assert (
        await provider.resolve_secret(
            SecretReference(provider="local", name="rotating", version="latest")
        )
        == "two"
    )
    assert await provider.delete_secret(first) is True
    assert await provider.delete_secret(first) is False


async def test_resolve_failure_audits_reference_without_secret_value(
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SECRET_PROVIDER", "local")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    secrets_factory._provider = None
    secrets_factory._provider_key = None
    ref = SecretReference(provider="local", name="missing-audited", version="latest")
    with pytest.raises(IntegrationAuthError):
        await resolve_secret(db_session, ref)
    event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.resource_type == "secret_reference",
            AuditEvent.status == "failure",
        )
    )
    assert event is not None
    assert event.details == {"reference": ref.render()}
    secrets_factory._provider = None
    secrets_factory._provider_key = None


async def test_resolve_failure_audit_survives_caller_rollback(
    committed_db_session_factory,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SECRET_PROVIDER", "local")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    secrets_factory._provider = None
    secrets_factory._provider_key = None
    ref = SecretReference(provider="local", name="missing-durable", version="latest")

    async with committed_db_session_factory() as caller_db:
        with pytest.raises(IntegrationAuthError):
            await resolve_secret(caller_db, ref)
        await caller_db.rollback()

    async with committed_db_session_factory() as verify_db:
        event = await verify_db.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_type == "secret_reference",
                AuditEvent.status == "failure",
                AuditEvent.details["reference"].astext == ref.render(),
            )
        )
        assert event is not None
        await verify_db.execute(delete(AuditEvent).where(AuditEvent.id == event.id))
        await verify_db.commit()

    secrets_factory._provider = None
    secrets_factory._provider_key = None


async def test_write_and_delete_operations_audit_reference_only(
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SECRET_PROVIDER", "local")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path / "storage"))
    secrets_factory._provider = None
    secrets_factory._provider_key = None
    ref = await write_secret(db_session, name="audited-secret", value="never-audited-value")
    assert await delete_secret(db_session, ref) is True
    events = list(
        (
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.resource_type == "secret_reference")
            )
        ).all()
    )
    assert [event.action for event in events] == ["create", "delete"]
    rendered = repr([event.details for event in events])
    assert "never-audited-value" not in rendered
    assert ref.render() in rendered
    secrets_factory._provider = None
    secrets_factory._provider_key = None
