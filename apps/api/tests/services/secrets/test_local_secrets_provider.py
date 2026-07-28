"""Encrypted local secrets provider behavior."""

import asyncio
import multiprocessing
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from core.exceptions.integration import IntegrationCredentialUnavailableError
from core.settings import settings
from models.audit_event import AuditEvent
from services.secrets import delete_secret, factory as secrets_factory, resolve_secret, write_secret
from services.secrets.domain import SecretReference
from services.secrets.providers.local import LocalSecretsProvider
from services.secrets.utils import secret_environment_name

pytestmark = pytest.mark.asyncio


def _write_versions_in_process(store_path: str, count: int) -> None:
    async def write() -> None:
        provider = LocalSecretsProvider(store_path=store_path)
        for index in range(count):
            await provider.write_secret("concurrent", f"value-{index}")

    asyncio.run(write())


async def test_env_resolution_and_encrypted_file_round_trip(tmp_path, monkeypatch) -> None:
    provider = LocalSecretsProvider(store_path=tmp_path / "secrets.enc.json")
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
    provider = LocalSecretsProvider(store_path=tmp_path / "secrets.enc.json")
    with pytest.raises(IntegrationCredentialUnavailableError):
        await provider.resolve_secret(
            SecretReference(provider="local", name="missing", version="latest")
        )


async def test_write_versions_and_delete(tmp_path) -> None:
    provider = LocalSecretsProvider(store_path=tmp_path / "secrets.enc.json")
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


async def test_relative_store_path_is_anchored_to_api_root(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    provider = LocalSecretsProvider(store_path=".local/path-stability.enc.json")

    assert provider.store_path.is_absolute()
    assert provider.store_path.name == "path-stability.enc.json"
    assert tmp_path not in provider.store_path.parents


@pytest.mark.parametrize("payload", ["not-ciphertext", ""])
async def test_malformed_store_raises_operational_error(tmp_path, payload) -> None:
    store_path = tmp_path / "secrets.enc.json"
    store_path.write_text(payload, encoding="utf-8")
    provider = LocalSecretsProvider(store_path=store_path)

    with pytest.raises(IntegrationCredentialUnavailableError):
        await provider.resolve_secret(
            SecretReference(provider="local", name="missing", version="latest")
        )


async def test_unreadable_store_raises_operational_error(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "secrets.enc.json"
    store_path.write_text("ciphertext", encoding="utf-8")
    provider = LocalSecretsProvider(store_path=store_path)

    def unreadable(*args, **kwargs):
        raise PermissionError("not readable")

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(IntegrationCredentialUnavailableError):
        await provider.resolve_secret(
            SecretReference(provider="local", name="missing", version="latest")
        )


async def test_independent_processes_do_not_lose_versions(tmp_path) -> None:
    store_path = tmp_path / "secrets.enc.json"
    process_context = multiprocessing.get_context("spawn")
    processes = [
        process_context.Process(
            target=_write_versions_in_process,
            args=(str(store_path), 6),
        )
        for _index in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    provider = LocalSecretsProvider(store_path=store_path)
    assert len(provider._read_store()["concurrent"]) == 12
    assert oct(store_path.stat().st_mode & 0o777) == "0o600"


async def test_readers_never_observe_partial_writes(tmp_path) -> None:
    store_path = tmp_path / "secrets.enc.json"
    writer = LocalSecretsProvider(store_path=store_path)
    reader = LocalSecretsProvider(store_path=store_path)
    first = await writer.write_secret("rotating", "initial")

    async def write_many() -> None:
        for index in range(20):
            await writer.write_secret("rotating", f"value-{index}")

    async def read_many() -> None:
        for _index in range(40):
            value = await reader.resolve_secret(
                SecretReference(provider="local", name="rotating", version="latest")
            )
            assert value

    await asyncio.gather(write_many(), read_many())
    assert await reader.resolve_secret(first) == "initial"


async def test_resolve_failure_audits_reference_without_secret_value(
    db_session,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "SECRET_PROVIDER", "local")
    monkeypatch.setattr(settings, "LOCAL_SECRET_STORE_PATH", str(tmp_path / "secrets.enc.json"))
    secrets_factory._provider = None
    secrets_factory._provider_key = None
    ref = SecretReference(provider="local", name="missing-audited", version="latest")
    with pytest.raises(IntegrationCredentialUnavailableError):
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
    monkeypatch.setattr(settings, "LOCAL_SECRET_STORE_PATH", str(tmp_path / "secrets.enc.json"))
    secrets_factory._provider = None
    secrets_factory._provider_key = None
    ref = SecretReference(provider="local", name="missing-durable", version="latest")

    async with committed_db_session_factory() as caller_db:
        with pytest.raises(IntegrationCredentialUnavailableError):
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
    monkeypatch.setattr(settings, "LOCAL_SECRET_STORE_PATH", str(tmp_path / "secrets.enc.json"))
    secrets_factory._provider = None
    secrets_factory._provider_key = None
    ref = await write_secret(db_session, name="audited-secret", value="never-audited-value")
    assert await delete_secret(db_session, ref) is True
    events = list(
        (
            await db_session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.resource_type == "secret_reference",
                    AuditEvent.details["reference"].astext == ref.render(),
                )
                .order_by(AuditEvent.occurred_at, AuditEvent.id)
            )
        ).all()
    )
    assert [event.action for event in events] == ["create", "delete"]
    rendered = repr([event.details for event in events])
    assert "never-audited-value" not in rendered
    assert ref.render() in rendered
    secrets_factory._provider = None
    secrets_factory._provider_key = None
